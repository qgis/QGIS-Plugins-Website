import re

import requests
from django.http import HttpRequest


def extract_version(tag):
    """
    Extracts the major and minor version from a given tag.

    The tag should be in the format of x.y.z where x, y, and z are
    numbers representing major, minor, and patch versions respectively.

    Args:
       tag (str): The version tag to be processed.

    Returns:
       str: The major and minor version as x.y, or None if no match.
    """
    match = re.search(r"(\d+\.\d+\.\d+)", tag)
    if match:
        version = match.group(1)
        version_parts = version.split(".")
        return ".".join(version_parts[:-1])
    else:
        return None


def get_qgis_versions():
    """
    Fetches all releases from the QGIS GitHub repository and extracts their
    major and minor versions.

    Returns:
        list: A list of unique major and minor versions of the releases.

    Raises:
        Exception: If the request to the GitHub API fails.
    """
    url = "https://api.github.com/repos/qgis/QGIS/releases"
    response = requests.get(url)
    if response.status_code != 200:
        raise Exception("Request failed")
    releases = response.json()
    all_versions = []
    for release in releases:
        tag_name = release["tag_name"].replace("_", ".")
        version = extract_version(tag_name)
        if version not in all_versions:
            all_versions.append(version)
    url = "https://qgis.org/version.json"
    response = requests.get(url)
    if response.status_code != 200:
        raise Exception("Request failed")
    releases = response.json()
    version = releases["dev"]["version"]
    if version not in all_versions:
        all_versions.insert(0, version)
    return all_versions


def parse_remote_addr(request: HttpRequest) -> str:
    """Extract client IP from request.

    X-Forwarded-For is deliberately not read here: it is supplied by the client
    and is forgeable. middleware.XForwardedForMiddleware is the single place
    that decides how much of that header can be trusted, and it has already
    normalised REMOTE_ADDR by the time a view runs.
    """
    return request.META.get("REMOTE_ADDR", "")


# Release channel names accepted wherever a QGIS version number is expected.
# These are fixed by the version.qgis.org payload rather than by deployment, so
# they live here next to the function that resolves them rather than in
# settings. generate_plugins_xml caches one feed per label as
# plugins_<label>.xml, and _clean_qgis_version allows them through so those
# cached feeds stay reachable.
QGIS_VERSION_LABELS = ("latest", "stable", "ltr")


def get_version_from_label(param):
    """
    Fetches the QGIS version based on the given parameter.

    Args:
        param (str): The parameter to determine which version to fetch.
                     Accepts one of QGIS_VERSION_LABELS.

    Returns:
        str: The major and minor version of QGIS.

    Raises:
        ValueError: If the parameter value is invalid.
        Exception: If the request to the QGIS version service fails or the version is not found.
    """
    url = "https://version.qgis.org/version.json"

    response = requests.get(url)
    if response.status_code != 200:
        raise Exception("Request failed")

    content = response.json()
    param = param.lower()

    if param == "stable":
        param = "ltr"

    if param in content:
        version_info = content[param]
        return version_info["version"]
    return None
