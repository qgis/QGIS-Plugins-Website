import os
from unittest import mock

import requests
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import InMemoryUploadedFile
from django.test import TestCase
from plugins.validator import _check_url_link, validator

TESTFILE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "testfiles"))


class TestValidatorMetadataPlugins(TestCase):
    def setUp(self):
        invalid_plugins = os.path.join(TESTFILE_DIR, "invalid_metadata_link.zip")
        invalid_url_scheme_plugins = os.path.join(
            TESTFILE_DIR, "invalid_url_scheme.zip"
        )
        web_not_exist_plugins = os.path.join(TESTFILE_DIR, "web_not_exist.zip")
        valid_plugins = os.path.join(TESTFILE_DIR, "valid_metadata_link.zip")
        timeout_plugin_link = os.path.join(TESTFILE_DIR, "timeout_plugin_link.zip_")
        self.valid_metadata_link = open(valid_plugins, "rb")
        self.invalid_metadata_link = open(invalid_plugins, "rb")
        self.web_not_exist = open(web_not_exist_plugins, "rb")
        self.invalid_url_scheme = open(invalid_url_scheme_plugins, "rb")
        self.timeout_plugin_link = open(timeout_plugin_link, "rb")

    def tearDown(self):
        self.valid_metadata_link.close()
        self.invalid_metadata_link.close()
        self.invalid_url_scheme.close()
        self.web_not_exist.close()
        self.timeout_plugin_link.close()

    def test_valid_metadata(self):
        self.assertTrue(
            validator(
                InMemoryUploadedFile(
                    self.valid_metadata_link,
                    field_name="tempfile",
                    name="testfile.zip",
                    content_type="application/zip",
                    size=39889,
                    charset="utf8",
                )
            )
        )

    def test_invalid_metadata_link_tracker_repo_homepage(self):
        """
        The invalid_metadata_link.zip contains metadata file with default link
        value.

        bug tracker : http://bugs
        repo :  http://repo
        homepage : http://homepage
        """

        self.assertRaises(
            ValidationError,
            validator,
            InMemoryUploadedFile(
                self.invalid_metadata_link,
                field_name="tempfile",
                name="testfile.zip",
                content_type="application/zip",
                size=39889,
                charset="utf8",
            ),
        )

    def test_invalid_metadata_url_scheme(self):
        """
        The invalid_url_scheme.zip contains metadata file with
        invalid scheme.

        bug tracker : https  ://www.example.com/invalid-url-scheme
        repo :  https://plugins.qgis.org/
        homepage: https://plugins.qgis.org/
        """

        self.assertRaises(
            ValidationError,
            validator,
            InMemoryUploadedFile(
                self.invalid_url_scheme,
                field_name="tempfile",
                name="testfile.zip",
                content_type="application/zip",
                size=39889,
                charset="utf8",
            ),
        )

    def test_invalid_metadata_web_does_not_exist(self):
        """
        The invalid_url_scheme.zip contains metadata file with
        invalid scheme.

        bug tracker : http://www.example.com
        repo :  http://www.example.com/this-not-exist
        homepage: http://www.example.com
        """

        self.assertRaises(
            ValidationError,
            validator,
            InMemoryUploadedFile(
                self.web_not_exist,
                field_name="tempfile",
                name="testfile.zip",
                content_type="application/zip",
                size=39889,
                charset="utf8",
            ),
        )

    def test_timeout_plugin_link(self):
        """
        The timeout_plugin_link.zip contains metadata file with
        invalid scheme.
        bug tracker : http://www.example.com
        repo :  http://www.example.com/
        homepage: http://www.google.com:81/
        """
        self.assertRaises(
            ValidationError,
            validator,
            InMemoryUploadedFile(
                self.timeout_plugin_link,
                field_name="tempfile",
                name="testfile.zip",
                content_type="application/zip",
                size=39889,
                charset="utf8",
            ),
        )


    @mock.patch("requests.get", side_effect=requests.exceptions.SSLError())
    def test_check_url_link_ssl_error(self, mock_request):
        urls = [{'url': "http://example.com/", 'forbidden_url': "forbidden_url", 'metadata_attr': "metadata attribute"}]
        self.assertIsNone(_check_url_link(urls))

    @mock.patch("requests.get", side_effect=requests.exceptions.HTTPError())
    def test_check_url_link_does_not_exist(self, mock_request):
        urls = [{'url': "http://example.com/", 'forbidden_url': "forbidden_url", 'metadata_attr': "metadata attribute"}]
        self.assertIsNone(_check_url_link(urls))


class TestCheckUrlLinkFollowsRedirects(TestCase):
    """Regression tests for issue #342: URL validation must follow redirects
    (e.g. GitLab moving /-/issues to /-/work-items) instead of rejecting them."""

    URLS = [{
        'url': "https://gitlab.com/example/-/issues",
        'forbidden_url': "forbidden_url",
        'metadata_attr': "tracker",
    }]

    def _make_response(self, status_code):
        response = mock.Mock()
        response.status_code = status_code
        return response

    @mock.patch("requests.head")
    def test_head_calls_pass_allow_redirects(self, mock_head):
        mock_head.return_value = self._make_response(200)
        self.assertIsNone(_check_url_link(self.URLS))
        # Both the timeout check and the existence check should opt in to
        # following redirects, otherwise a 3xx response would be treated as
        # the final status.
        self.assertGreaterEqual(mock_head.call_count, 2)
        for call in mock_head.call_args_list:
            self.assertTrue(
                call.kwargs.get("allow_redirects"),
                "requests.head must be called with allow_redirects=True",
            )

    @mock.patch("requests.head")
    def test_redirect_to_valid_url_is_accepted(self, mock_head):
        # When allow_redirects=True, requests transparently follows the
        # redirect chain and returns the final response's status code.
        mock_head.return_value = self._make_response(200)
        self.assertIsNone(_check_url_link(self.URLS))

    @mock.patch("requests.head")
    def test_redirect_to_broken_url_is_rejected(self, mock_head):
        # If the final URL after redirects is itself broken, validation
        # must still fail.
        mock_head.return_value = self._make_response(404)
        with self.assertRaises(ValidationError):
            _check_url_link(self.URLS)

    @mock.patch("requests.head")
    def test_ssl_error_retries_with_allow_redirects(self, mock_head):
        # The SSL fallback path (verify=False) lives in error_check_if_exist,
        # which runs after the timeout check passes. Both the retry and its
        # redirect handling must stay intact.
        mock_head.side_effect = [
            self._make_response(200),         # timeout check passes
            requests.exceptions.SSLError(),   # existence check trips SSL error
            self._make_response(200),         # SSL-fallback retry succeeds
        ]
        self.assertIsNone(_check_url_link(self.URLS))
        ssl_retry_call = mock_head.call_args_list[2]
        self.assertTrue(ssl_retry_call.kwargs.get("allow_redirects"))
        self.assertFalse(ssl_retry_call.kwargs.get("verify"))


class TestValidatorForbiddenFileFolder(TestCase):
    """Test if zipfile is not containing forbidden folders and files """

    def setUp(self) -> None:
        valid_plugins = os.path.join(TESTFILE_DIR, "valid_metadata_link.zip")
        self.valid_metadata_link = open(valid_plugins, "rb")
        self.package = InMemoryUploadedFile(
            self.valid_metadata_link,
            field_name="tempfile",
            name="testfile.zip",
            content_type="application/zip",
            size=1234,
            charset="utf8",
        )

    def tearDown(self):
        self.valid_metadata_link.close()

    @mock.patch("zipfile.ZipFile.namelist")
    def test_zipfile_with_pyc_file(self, mock_namelist):
        mock_namelist.return_value = [".pyc"]
        with self.assertRaisesMessage(
            Exception, "For security reasons, zip file cannot contain .pyc file"
        ):
            validator(self.package)

    @mock.patch("zipfile.ZipFile.namelist")
    def test_zipfile_with_MACOSX(self, mock_namelist):
        mock_namelist.return_value = ["__MACOSX/"]
        with self.assertRaisesMessage(
            Exception,
            (
                "For security reasons, zip file cannot contain <strong> '__MACOSX' </strong> directory. "
                "However, there is one present at the root of the archive."
             ),
        ):
            validator(self.package)

    @mock.patch("zipfile.ZipFile.namelist")
    def test_zipfile_with_pycache(self, mock_namelist):
        mock_namelist.return_value = ["__pycache__/"]
        with self.assertRaisesMessage(
            Exception,
            (
                "For security reasons, zip file cannot contain <strong> '__pycache__' </strong> directory. "
                "However, there is one present at the root of the archive."
            ),
        ):
            validator(self.package)

    @mock.patch("zipfile.ZipFile.namelist")
    def test_zipfile_with_pycache_in_children(self, mock_namelist):
        mock_namelist.return_value = ["path/to/__pycache__/"]
        with self.assertRaisesMessage(
            Exception,
            (
                "For security reasons, zip file cannot contain <strong> '__pycache__' </strong> directory. "
                "However, it has been found at <strong> 'path/to/__pycache__/' </strong>."
            ),
        ):
            validator(self.package)

    @mock.patch("zipfile.ZipFile.namelist")
    def test_zipfile_with_git(self, mock_namelist):
        mock_namelist.return_value = [".git"]
        with self.assertRaisesMessage(
            Exception,
            (
                "For security reasons, zip file cannot contain <strong> '.git' </strong> directory. "
                "However, there is one present at the root of the archive."
            ),
        ):
            validator(self.package)

    @mock.patch("zipfile.ZipFile.namelist")
    def test_zipfile_with_gitignore(self, mock_namelist):
        """test if .gitignore will not raise ValidationError"""
        mock_namelist.return_value = [".gitignore"]
        with self.assertRaises(ValidationError) as cm:
            validator(self.package)
        exception = cm.exception
        self.assertNotEqual(
            exception.message,
            "For security reasons, zip file cannot contain <strong> '.git' </strong> directory. ",
            "However, there is one present at the root of the archive."
        )


class TestValidatorInvalidPackageName(TestCase):
    """Test if plugin's directory is not PEP8 compliant """

    def setUp(self) -> None:
        invalid_package_name = os.path.join(TESTFILE_DIR, "invalid_package_name.zip_")
        self.plugin_package = open(invalid_package_name, "rb")

    def tearDown(self):
        self.plugin_package.close()

    # Package name does not match PEP8
    def test_new_plugin_invalid_package_name(self):
        self.assertRaises(
            ValidationError,
            validator,
            InMemoryUploadedFile(
                self.plugin_package,
                field_name="tempfile",
                name="testfile.zip",
                content_type="application/zip",
                size=39889,
                charset="utf8",
            ),
            is_new=True
        )


class TestLicenseValidator(TestCase):
    """Test if zipfile contains LICENSE file """    

    def setUp(self) -> None:
        plugin_without_license = os.path.join(TESTFILE_DIR, "plugin_without_license.zip_")
        self.plugin_package = open(plugin_without_license, "rb")

    def tearDown(self):
        self.plugin_package.close()

    # License file is required
    def test_new_plugin_without_license(self):
        self.assertRaises(
            ValidationError,
            validator,
            InMemoryUploadedFile(
                self.plugin_package,
                field_name="tempfile",
                name="testfile.zip",
                content_type="application/zip",
                size=39889,
                charset="utf8",
            )
        )

class TestMultipleParentFoldersValidator(TestCase):
    """Test if zipfile contains multiple parent folders """    

    def setUp(self) -> None:
        multi_parents_plugin = os.path.join(TESTFILE_DIR, "multi_parents_plugin.zip_")
        self.multi_parents_plugin_package = open(multi_parents_plugin, "rb")
        valid_plugin = os.path.join(TESTFILE_DIR, "valid_plugin.zip_")
        self.single_parent_plugin_package = open(valid_plugin, "rb")

    def tearDown(self):
        self.multi_parents_plugin_package.close()
        self.single_parent_plugin_package.close()

    def _get_value_by_attribute(self, attribute, data):
        for key, value in data:
            if key == attribute:
                return value
        return None
    def test_plugin_with_multiple_parents(self):
        result =  validator(
            InMemoryUploadedFile(
                self.multi_parents_plugin_package,
                field_name="tempfile",
                name="testfile.zip",
                content_type="application/zip",
                size=39889,
                charset="utf8",
            )
        )
        multiple_parent_folders = self._get_value_by_attribute('multiple_parent_folders', result)
        self.assertIsNotNone(multiple_parent_folders)

    def test_plugin_with_single_parent(self):
        result =  validator(
            InMemoryUploadedFile(
                self.single_parent_plugin_package,
                field_name="tempfile",
                name="testfile.zip",
                content_type="application/zip",
                size=39889,
                charset="utf8",
            )
        )
        multiple_parent_folders = self._get_value_by_attribute('multiple_parent_folders', result)
        self.assertIsNone(multiple_parent_folders)


class TestPathWithBackslashValidator(TestCase):
    def setUp(self) -> None:
        path_with_backslash = os.path.join(TESTFILE_DIR, "path_with_backslash.zip_")
        self.path_with_backslash = open(path_with_backslash, "rb")

    def tearDown(self):
        self.path_with_backslash.close()

    def test_path_with_backslash(self):
        """
        The path_with_backslash.zip contains file with
        path with backslash.
        """
        self.assertRaises(
            ValidationError,
            validator,
            InMemoryUploadedFile(
                self.path_with_backslash,
                field_name="tempfile",
                name="testfile.zip",
                content_type="application/zip",
                size=39889,
                charset="utf8",
            ),
        )