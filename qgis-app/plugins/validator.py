"""
Plugin validator class

"""

import codecs
import configparser
import logging
import mimetypes
import os
import re
import zipfile
from io import StringIO
from urllib.parse import urlparse

import requests
from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.forms import ValidationError
from django.utils.translation import gettext_lazy as _
from plugins.safe_http import BlockedAddressError, build_safe_session

logger = logging.getLogger(__name__)

PLUGIN_MAX_UPLOAD_SIZE = getattr(settings, "PLUGIN_MAX_UPLOAD_SIZE", 25000000)  # 25 mb
PLUGIN_REQUIRED_METADATA = getattr(
    settings,
    "PLUGIN_REQUIRED_METADATA",
    (
        "name",
        "description",
        "version",
        "qgisMinimumVersion",
        "author",
        "email",
        "about",
        "tracker",
        "repository",
    ),
)

PLUGIN_OPTIONAL_METADATA = getattr(
    settings,
    "PLUGIN_OPTIONAL_METADATA",
    (
        "homepage",
        "changelog",
        "qgisMaximumVersion",
        "tags",
        "deprecated",
        "experimental",
        "external_deps",
        "server",
    ),
)
PLUGIN_BOOLEAN_METADATA = getattr(
    settings,
    "PLUGIN_BOOLEAN_METADATA",
    ("experimental", "deprecated", "server"),
)

URL_CHECK_TIMEOUT = getattr(settings, "URL_CHECK_TIMEOUT", 10)  # seconds per attempt

# A url that stalls once is tried again before the upload is rejected. Keep the
# product of timeout and attempts below the web server request timeout.
URL_CHECK_ATTEMPTS = getattr(settings, "URL_CHECK_ATTEMPTS", 2)

# https://stackoverflow.com/a/41950438/10268058
# add the headers parameter to make the request appears like coming
# from browser, otherwise some websites will return 403
URL_CHECK_HEADERS = {
    "User-Agent": getattr(
        settings,
        "URL_CHECK_USER_AGENT",
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0.0.0 Safari/537.36",
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# Some hosts (Codeberg, for instance) actively reject requests that claim to be
# a browser but are not, answering 403 to the headers above. Retry those with an
# honest, identifiable user agent before declaring the url unreachable.
URL_CHECK_FALLBACK_HEADERS = {
    "User-Agent": getattr(
        settings,
        "URL_CHECK_FALLBACK_USER_AGENT",
        "QGIS-Plugins-Website/1.0 (+https://plugins.qgis.org; link validator)",
    ),
    "Accept": "*/*",
}

# Statuses that usually mean "we do not like your client", not "this url is broken".
URL_CHECK_RETRY_STATUSES = (401, 403, 406, 409, 429)

# One session for every link check. Its adapter validates the real peer address
# of every connection, so a url that resolves or redirects to an internal host
# is refused at connect time rather than fetched.
_url_check_session = build_safe_session()


def _read_from_init(initcontent, initname):
    """
    Read metadata from __init__.py, raise ValidationError
    """
    metadata = []
    i = 0
    lines = initcontent.split("\n")
    while i < len(lines):
        if re.search(r"def\s+([^\(]+)", lines[i]):
            k = re.search(r"def\s+([^\(]+)", lines[i]).groups()[0]
            i += 1
            while i < len(lines) and lines[i] != "":
                if re.search(r"return\s+[\"']?([^\"']+)[\"']?", lines[i]):
                    metadata.append(
                        (
                            k,
                            re.search(
                                r"return\s+[\"']?([^\"']+)[\"']?", lines[i]
                            ).groups()[0],
                        )
                    )
                    break
                i += 1
        i += 1
    if not len(metadata):
        raise ValidationError(_("Cannot find valid metadata in %s") % initname)
    return metadata


def _check_required_metadata(metadata):
    """
    Checks if required metadata are in place, raise ValidationError if not found
    """

    missing_fields = [
        field
        for field in PLUGIN_REQUIRED_METADATA
        if field not in [item[0] for item in metadata]
    ]
    if len(missing_fields) > 0:
        missing_fields_str = ", ".join(missing_fields)
        raise ValidationError(
            _(
                f'Cannot find metadata <strong>{missing_fields_str}</strong> in metadata source <code>{dict(metadata).get("metadata_source")}</code>.<br />For further informations about metadata, please see: <a target="_blank"  href="https://docs.qgis.org/testing/en/docs/pyqgis_developer_cookbook/plugins/plugins.html#metadata-txt">metadata documentation</a>'
            )
        )


def _check_url_link(urls):
    """
    Checks if all the url link is valid.
    """

    def error_check(url: str, forbidden_url: str) -> bool:
        # Check against forbidden_url
        if url == forbidden_url:
            return True

        # Check if parsed URL is valid
        try:
            parsed_url = urlparse(url)
            return not all([parsed_url.scheme, parsed_url.netloc])
        except Exception:
            return True

    def request_url(method, url: str, headers=URL_CHECK_HEADERS, **kwargs):
        # Every request goes through the guarded session, so a url that
        # resolves or redirects to an internal address is refused at connect
        # time. Certificate verification stays on: a url we cannot verify is
        # treated as unreachable, not quietly trusted.
        return method(
            url,
            headers=headers,
            timeout=URL_CHECK_TIMEOUT,
            allow_redirects=True,
            **kwargs,
        )

    def check_once(url: str):
        """
        One reachability attempt. Returns "ok", "timeout", or "unreachable".

        The caller turns any failure into the same message, so the reason stays
        here and is only written to the server log. Telling the uploader why a
        url failed, or that an internal host answered at all, would let an
        upload probe the server's own network.
        """
        try:
            response = request_url(_url_check_session.head, url)
            if response.status_code >= 400:
                # Some servers reject or mishandle HEAD requests (400, 403,
                # 405, ...) while serving the very same url over GET, so
                # confirm with a GET before declaring the url broken.
                response = request_url(_url_check_session.get, url, stream=True)
                response.close()
            if response.status_code in URL_CHECK_RETRY_STATUSES:
                # The host is up but refuses our browser-like user agent, ask
                # again identifying ourselves honestly.
                response = request_url(
                    _url_check_session.get,
                    url,
                    headers=URL_CHECK_FALLBACK_HEADERS,
                    stream=True,
                )
                response.close()
        except requests.exceptions.Timeout:
            logger.info("Link check timed out for %s", url)
            return "timeout"
        except BlockedAddressError as e:
            # An internal address. Logged for operators, but indistinguishable
            # from any other failure in what the uploader sees.
            logger.warning(
                "Link check refused: %s resolves to blocked address %s", url, e
            )
            return "unreachable"
        except Exception as e:
            logger.info("Link check failed for %s: %s", url, type(e).__name__)
            return "unreachable"
        if response.status_code < 400:
            return "ok"
        logger.info("Link check got HTTP %s for %s", response.status_code, url)
        return "unreachable"

    def is_reachable(url: str) -> bool:
        """
        True when the url answers. A stall is retried before it fails the
        upload: hosts such as Codeberg intermittently take a very long time to
        answer, and a single slow response should not block a plugin release.
        """
        for _attempt in range(URL_CHECK_ATTEMPTS):
            result = check_once(url)
            if result != "timeout":
                return result == "ok"
        return False

    url_error = [
        url_item["metadata_attr"]
        for url_item in urls
        if error_check(url_item["url"], url_item["forbidden_url"])
    ]
    if len(url_error) > 0:
        url_error_str = ", ".join(url_error)
        raise ValidationError(
            _(
                f"Please provide valid url link for the following key(s) in the metadata source: <strong>{url_error_str}</strong>. "
            )
        )

    # One message for every kind of failure. It names which metadata fields
    # failed, since the uploader supplied those values and seeing them is not a
    # disclosure, but never the reason, the status, or the address a url
    # resolved to. Varying any of those would turn this check into a way to map
    # the server's network.
    unreachable = [
        url_item["metadata_attr"]
        for url_item in urls
        if not is_reachable(url_item["url"])
    ]
    if len(unreachable) > 0:
        fields = ", ".join(unreachable)
        raise ValidationError(
            _(
                "We could not reach the link you gave for: <strong>%(fields)s</strong>. "
                "Check that each one opens in a browser and points to a public address."
            )
            % {"fields": fields}
        )


def validate_package_name_pep8(package_name: str):
    """
    Checks that the plugin's top level directory name is PEP 8 compliant,
    i.e. a valid Python identifier.

    This is only enforced for new plugins: plugins registered before this
    rule was introduced must still be able to publish new versions, since
    their package name cannot be changed without appearing as a brand new
    plugin to their users.
    """
    if not package_name.isidentifier():
        raise ValidationError(
            _(
                "The name of the top level directory inside the zip package must be PEP 8 compliant: "
                "a valid Python identifier, which means it must start with a letter or underscore, "
                "and can only contain letters, digits, and underscores."
            )
        )


def validator(package, is_new: bool = False):
    """
    Analyzes a zipped file, returns metadata if success, False otherwise.
    If the new icon metadata is found, an inmemory file object is also returned

    Current checks:

        * size <= PLUGIN_MAX_UPLOAD_SIZE
        * zip contains __init__.py in first level dir
        * Check for LICENSE file
        * mandatory metadata: ('name', 'description', 'version', 'qgisMinimumVersion', 'author', 'email')
        * package_name regexp: [A-Za-z][A-Za-z0-9-_]+
        * author regexp: [^/]+
        * New plugins package_name is PEP8 compliant

    """
    try:
        if package.size > PLUGIN_MAX_UPLOAD_SIZE:
            raise ValidationError(
                _("File is too big. Max size is %s Megabytes")
                % (PLUGIN_MAX_UPLOAD_SIZE / 1000000)
            )
    except AttributeError:
        if package.len > PLUGIN_MAX_UPLOAD_SIZE:
            raise ValidationError(
                _("File is too big. Max size is %s Megabytes")
                % (PLUGIN_MAX_UPLOAD_SIZE / 1000000)
            )

    try:
        zip = zipfile.ZipFile(package)
    except:
        raise ValidationError(_("Could not unzip file."))
    for zname in zip.namelist():
        if zname.find("..") != -1 or zname.find(os.path.sep) == 0:
            raise ValidationError(
                _(
                    "For security reasons, zip file cannot contain path "
                    "information (found '{}')".format(zname)
                )
            )
        if zname.find(".pyc") != -1:
            raise ValidationError(
                _("For security reasons, zip file cannot contain .pyc file")
            )
        for forbidden_dir in ["__MACOSX", ".git", "__pycache__"]:
            dir_name_list = zname.split("/")
            if forbidden_dir in dir_name_list:
                if forbidden_dir == dir_name_list[0]:
                    raise ValidationError(
                        _(
                            "For security reasons, zip file "
                            "cannot contain <strong> '%s' </strong> directory. However, there is one present at the root of the archive."
                            % (forbidden_dir,)
                        )
                    )
                raise ValidationError(
                    _(
                        "For security reasons, zip file "
                        "cannot contain <strong> '%s' </strong> directory. However, it has been found at <strong> '%s' </strong>."
                        % (forbidden_dir, zname)
                    )
                )
    bad_file = zip.testzip()
    if bad_file:
        zip.close()
        del zip
        try:
            raise ValidationError(
                _("Bad zip (maybe a CRC error) on file %s") % bad_file
            )
        except UnicodeDecodeError:
            raise ValidationError(
                _("Bad zip (maybe unicode filename) on file %s") % bad_file,
                errors="replace",
            )

    # Metadata list, also usefull to pass warnings to the main view
    metadata = []

    namelist = zip.namelist()
    # Check if the zip file contains multiple parent folders
    # If it is, show a warning for now
    try:
        parent_folders = list(set([str(name).split("/")[0] for name in namelist]))
        if len(parent_folders) > 1:
            metadata.append(("multiple_parent_folders", ", ".join(parent_folders)))
    except:
        pass

    # Check if the zip namelist contains backslashes or drive letters, which is not allowed.
    for name in namelist:
        if "\\" in name:
            raise ValidationError(
                _(
                    "Your archive does not conform to the ZIP specification, "
                    "it cannot contain backslashes in file names (found '{}'). "
                    "Please try again with a valid ZIP file (or use a different archiving tool).".format(
                        name
                    )
                )
            )
        if re.match(r"^[A-Za-z]:", name):
            raise ValidationError(
                _(
                    "Your archive does not conform to the ZIP specification, "
                    "it cannot contain drive letters in file names (found '{}'). "
                    "Please try again with a valid ZIP file (or use a different archiving tool).".format(
                        name
                    )
                )
            )

    # Checks that package_name  exists
    try:
        package_name = namelist[0][: namelist[0].index("/")]
    except:
        raise ValidationError(
            _(
                "Cannot find a folder inside the compressed package: this does not seems a valid plugin"
            )
        )
    # Check if package_name is PEP 8 compliant
    if is_new:
        validate_package_name_pep8(package_name)

    # Cuts the trailing slash
    if package_name.endswith("/"):
        package_name = package_name[:-1]
    initname = package_name + "/__init__.py"
    metadataname = package_name + "/metadata.txt"
    if initname not in namelist and metadataname not in namelist:
        raise ValidationError(
            _(
                "Cannot find __init__.py or metadata.txt in the compressed package: this does not seems a valid plugin (I searched for %s and %s)"
            )
            % (initname, metadataname)
        )

    # Checks for __init__.py presence
    if initname not in namelist:
        raise ValidationError(_("Cannot find __init__.py in plugin package."))

    # First parse metadata.txt
    if metadataname in namelist:
        try:
            parser = configparser.ConfigParser()
            parser.optionxform = str
            parser.read_file(StringIO(codecs.decode(zip.read(metadataname), "utf8")))
            if not parser.has_section("general"):
                raise ValidationError(
                    _("Cannot find a section named 'general' in %s") % metadataname
                )
            metadata.extend(parser.items("general"))
        except Exception as e:
            raise ValidationError(_("Errors parsing %s. %s") % (metadataname, e))
        metadata.append(("metadata_source", "metadata.txt"))
    else:
        # Then parse __init__
        # Ugly RE: regexp guru wanted!
        initcontent = zip.read(initname).decode("utf8")
        metadata.extend(_read_from_init(initcontent, initname))
        if not metadata:
            raise ValidationError(_("Cannot find valid metadata in %s") % initname)
        metadata.append(("metadata_source", "__init__.py"))

    _check_required_metadata(metadata)

    # Process Icon
    try:
        # Strip leading dir for ccrook plugins
        if dict(metadata)["icon"].startswith("./"):
            icon_path = dict(metadata)["icon"][2:]
        else:
            icon_path = dict(metadata)["icon"]
        icon = zip.read(package_name + "/" + icon_path)
        icon_file = SimpleUploadedFile(
            dict(metadata)["icon"], icon, mimetypes.guess_type(dict(metadata)["icon"])
        )
    except:
        icon_file = None

    metadata.append(("icon_file", icon_file))

    # Check for deprecated supportsQt6 flag
    if "supportsQt6" in dict(metadata):
        metadata.append(("supportsQt6_deprecated", True))

    # Transforms booleans flags (experimental)
    for flag in PLUGIN_BOOLEAN_METADATA:
        if flag in dict(metadata):
            metadata[metadata.index((flag, dict(metadata)[flag]))] = (
                flag,
                dict(metadata)[flag].lower() == "true"
                or dict(metadata)[flag].lower() == "yes"
                or dict(metadata)[flag].lower() == "1",
            )

    # Adds package_name
    if not re.match(r"^[A-Za-z][A-Za-z0-9-_]+$", package_name):
        raise ValidationError(
            _(
                "The name of the top level directory inside the zip package must start with an ASCII letter and can only contain ASCII letters, digits and the signs '-' and '_'."
            )
        )
    metadata.append(("package_name", package_name))

    # Last temporary rule, check if mandatory metadata are also in __init__.py
    # fails if it is not
    min_qgs_version = dict(metadata).get("qgisMinimumVersion")
    dict(metadata).get("qgisMaximumVersion")
    if (
        tuple(min_qgs_version.split(".")) < tuple("1.8".split("."))
        and metadataname in namelist
    ):
        initcontent = zip.read(initname).decode("utf8")
        try:
            initmetadata = _read_from_init(initcontent, initname)
            initmetadata.append(("metadata_source", "__init__.py"))
            _check_required_metadata(initmetadata)
        except ValidationError as e:
            raise ValidationError(
                _(
                    "qgisMinimumVersion is set to less than  1.8 (%s) and there were errors reading metadata from the __init__.py file. This can lead to errors in versions of QGIS less than 1.8, please either set the qgisMinimumVersion to 1.8 or specify the metadata also in the __init__.py file. Reported error was: %s"
                )
                % (min_qgs_version, ",".join(e.messages))
            )
    # check url_link
    urls_to_check = [
        {
            "url": dict(metadata).get("tracker"),
            "forbidden_url": "http://bugs",
            "metadata_attr": "tracker",
        },
        {
            "url": dict(metadata).get("repository"),
            "forbidden_url": "http://repo",
            "metadata_attr": "repository",
        },
        {
            "url": dict(metadata).get("homepage"),
            "forbidden_url": "http://homepage",
            "metadata_attr": "homepage",
        },
    ]

    _check_url_link(urls_to_check)

    # Checks for LICENSE file presence
    # Making it mandatory as of 03 June 2024
    # according to https://github.com/qgis/QGIS-Enhancement-Proposals/issues/279
    licensename = package_name + "/LICENSE"
    if licensename not in namelist:
        raise ValidationError(
            _(
                "Cannot find LICENSE in the plugin package. "
                "This file is required, please consider adding it to the plugin package."
            )
        )

    zip.close()
    del zip

    # Check author
    if "author" in dict(metadata):
        if not re.match(r"^[^/]+$", dict(metadata)["author"]):
            raise ValidationError(_("Author name cannot contain slashes."))

    # strip and check
    checked_metadata = []
    for k, v in metadata:
        try:
            if not (
                k in PLUGIN_BOOLEAN_METADATA
                or k in ("icon_file", "supportsQt6_deprecated")
            ):
                # v.decode('UTF-8')
                checked_metadata.append((k, v.strip()))
            else:
                checked_metadata.append((k, v))
        except UnicodeDecodeError as e:
            raise ValidationError(
                _(
                    "There was an error converting metadata '%s' to UTF-8 . Reported error was: %s"
                )
                % (k, e)
            )
    return checked_metadata
