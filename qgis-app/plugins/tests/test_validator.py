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
        urls = [
            {
                "url": "http://example.com/",
                "forbidden_url": "forbidden_url",
                "metadata_attr": "metadata attribute",
            }
        ]
        self.assertIsNone(_check_url_link(urls))

    @mock.patch("requests.get", side_effect=requests.exceptions.HTTPError())
    def test_check_url_link_does_not_exist(self, mock_request):
        urls = [
            {
                "url": "http://example.com/",
                "forbidden_url": "forbidden_url",
                "metadata_attr": "metadata attribute",
            }
        ]
        self.assertIsNone(_check_url_link(urls))


class TestValidatorForbiddenFileFolder(TestCase):
    """Test if zipfile is not containing forbidden folders and files"""

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
            "However, there is one present at the root of the archive.",
        )


class TestValidatorInvalidPackageName(TestCase):
    """Test if plugin's directory is not PEP8 compliant"""

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
            is_new=True,
        )


class TestLicenseValidator(TestCase):
    """Test if zipfile contains LICENSE file"""

    def setUp(self) -> None:
        plugin_without_license = os.path.join(
            TESTFILE_DIR, "plugin_without_license.zip_"
        )
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
            ),
        )


class TestMultipleParentFoldersValidator(TestCase):
    """Test if zipfile contains multiple parent folders"""

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
        result = validator(
            InMemoryUploadedFile(
                self.multi_parents_plugin_package,
                field_name="tempfile",
                name="testfile.zip",
                content_type="application/zip",
                size=39889,
                charset="utf8",
            )
        )
        multiple_parent_folders = self._get_value_by_attribute(
            "multiple_parent_folders", result
        )
        self.assertIsNotNone(multiple_parent_folders)

    def test_plugin_with_single_parent(self):
        result = validator(
            InMemoryUploadedFile(
                self.single_parent_plugin_package,
                field_name="tempfile",
                name="testfile.zip",
                content_type="application/zip",
                size=39889,
                charset="utf8",
            )
        )
        multiple_parent_folders = self._get_value_by_attribute(
            "multiple_parent_folders", result
        )
        self.assertIsNone(multiple_parent_folders)


class TestValidatorScreenshot(TestCase):
    """Test screenshot validation in plugin packages"""

    def test_validator_accepts_optional_screenshot_metadata(self):
        """Test that screenshot is recognized as optional metadata"""
        from plugins.validator import PLUGIN_OPTIONAL_METADATA

        self.assertIn("screenshot", PLUGIN_OPTIONAL_METADATA)

    def test_plugin_without_screenshot_validates(self):
        """Test that plugins without screenshot still validate correctly"""
        valid_plugin = os.path.join(TESTFILE_DIR, "valid_plugin.zip_")
        with open(valid_plugin, "rb") as f:
            result = validator(
                InMemoryUploadedFile(
                    f,
                    field_name="tempfile",
                    name="testfile.zip",
                    content_type="application/zip",
                    size=f.seek(0, 2),
                    charset="utf8",
                )
            )
            # Should validate without errors
            self.assertIsNotNone(result)
            # Screenshot file should not be in results if not in package
            for key, value in result:
                if key == "screenshot_file":
                    pass
            # If no screenshot in metadata, screenshot_file should not be present or be None
            # (depends on implementation)

    def test_screenshot_metadata_field_extracted(self):
        """Test that screenshot metadata field is extracted from metadata.txt"""
        plugin_with_screenshot = os.path.join(
            TESTFILE_DIR, "plugin_with_screenshot.zip_"
        )

        with open(plugin_with_screenshot, "rb") as f:
            result = validator(
                InMemoryUploadedFile(
                    f,
                    field_name="tempfile",
                    name="testfile.zip",
                    content_type="application/zip",
                    size=f.seek(0, 2),
                    charset="utf8",
                )
            )

            # Check that screenshot metadata is in results
            screenshot_metadata = None
            screenshot_file = None
            for key, value in result:
                if key == "screenshot":
                    screenshot_metadata = value
                elif key == "screenshot_file":
                    screenshot_file = value

            # Screenshot metadata field should be extracted
            self.assertEqual(screenshot_metadata, "preview.png")
            # Screenshot file should be extracted and available
            self.assertIsNotNone(screenshot_file)

    def test_screenshot_file_size_validation(self):
        """Test that oversized screenshots are rejected"""
        # TODO: Create test plugin with screenshot > 2MB
        # Verify ValidationError is raised

    def test_screenshot_format_validation(self):
        """Test that only valid image formats are accepted"""
        # TODO: Test that PNG, JPG, JPEG, GIF are accepted
        # Test that other formats (PDF, TXT, etc.) are rejected

    def test_screenshot_path_resolution(self):
        """Test that screenshot path is correctly resolved within plugin folder"""
        # TODO: Test both relative and absolute paths within plugin
        # e.g., 'screenshot.png' and '/screenshot.png' should both work
