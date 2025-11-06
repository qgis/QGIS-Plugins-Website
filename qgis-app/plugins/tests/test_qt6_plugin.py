import os
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from plugins.forms import PackageUploadForm
from plugins.models import Plugin, PluginVersion


def do_nothing(*args, **kwargs):
    pass


TESTFILE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "testfiles"))


class Qt6PluginTestCase(TestCase):
    """
    Test case for Qt6 plugin upload and verification that it appears
    in the new_qgis_ready endpoint.
    """

    fixtures = [
        "fixtures/auth.json",
    ]

    @override_settings(MEDIA_ROOT="api/tests")
    def setUp(self):
        self.client = Client()
        self.upload_url = reverse("plugin_upload")
        self.new_qgis_ready_url = reverse("new_qgis_ready_plugins")

        # Create a test user
        self.user = User.objects.create_user(
            username="qt6testuser", password="testpassword", email="qt6test@example.com"
        )

    @patch("plugins.tasks.generate_plugins_xml", new=do_nothing)
    @patch("plugins.validator._check_url_link", new=do_nothing)
    @override_settings(CURRENT_QGIS_MAJOR_VERSION="3")
    @override_settings(NEW_QGIS_MAJOR_VERSION="4")
    def test_qt6_plugin_upload_and_new_qgis_ready_endpoint(self):
        """
        Test that a Qt6-compatible plugin is uploaded successfully and
        appears in the new_qgis_ready endpoint.
        """
        # Log in the test user
        self.client.login(username="qt6testuser", password="testpassword")

        # Load the Qt6 test plugin
        valid_qt6_plugin = os.path.join(TESTFILE_DIR, "valid_qt6_plugin.zip_")

        # Check if the file exists
        self.assertTrue(
            os.path.exists(valid_qt6_plugin),
            f"Qt6 test plugin file not found at {valid_qt6_plugin}",
        )

        with open(valid_qt6_plugin, "rb") as file:
            uploaded_file = SimpleUploadedFile(
                "valid_qt6_plugin.zip_", file.read(), content_type="application/zip"
            )

        # Upload the Qt6 plugin
        response = self.client.post(
            self.upload_url,
            {
                "package": uploaded_file,
            },
        )

        # Check that the upload was successful (redirects on success)
        self.assertEqual(
            response.status_code, 302, f"Plugin upload failed. Response: {response}"
        )

        # Verify the plugin was created
        self.assertTrue(
            Plugin.objects.filter(name="Test Plugin").exists(),
            "Qt6 plugin was not created in the database",
        )

        # Get the created plugin
        plugin = Plugin.objects.get(name="Test Plugin")

        # Verify the plugin version was created
        self.assertTrue(
            PluginVersion.objects.filter(plugin=plugin).exists(),
            "Qt6 plugin version was not created",
        )

        # Get the plugin version
        plugin_version = PluginVersion.objects.get(plugin=plugin)

        # Verify the plugin version has supports_qt6=True
        self.assertTrue(
            plugin_version.supports_qt6,
            "Plugin version does not have supports_qt6=True",
        )

        # Verify min_qg_version is appropriate for QGIS 3+
        self.assertIsNotNone(
            plugin_version.min_qg_version,
            "Plugin version does not have min_qg_version set",
        )

        # Approve the plugin version so it appears in new_qgis_ready
        plugin_version.approved = True
        plugin_version.save()

        # Ensure the plugin is not deprecated
        plugin.deprecated = False
        plugin.save()

        # Access the new_qgis_ready endpoint
        response = self.client.get(self.new_qgis_ready_url)

        # Check that the endpoint is accessible
        self.assertEqual(
            response.status_code,
            200,
            f"new_qgis_ready endpoint returned status {response.status_code}",
        )

        # Verify the Qt6 plugin appears in the queryset
        plugins_in_response = response.context["object_list"]

        self.assertIn(
            plugin,
            plugins_in_response,
            "Qt6 plugin does not appear in new_qgis_ready endpoint",
        )

        # Additional verification: Check that the plugin matches all criteria
        # for new_qgis_ready_objects manager
        self.assertTrue(plugin_version.approved, "Plugin version is not approved")
        self.assertTrue(
            plugin_version.supports_qt6, "Plugin version does not support Qt6"
        )
        self.assertFalse(plugin.deprecated, "Plugin is deprecated")

        # Verify the min_qg_version meets the requirement
        current_major = getattr(settings, "CURRENT_QGIS_MAJOR_VERSION", "3")
        self.assertGreaterEqual(
            plugin_version.min_qg_version,
            f"{current_major}.0",
            f"Plugin min_qg_version {plugin_version.min_qg_version} is less than {current_major}.0",
        )

    @patch("plugins.tasks.generate_plugins_xml", new=do_nothing)
    @patch("plugins.validator._check_url_link", new=do_nothing)
    @override_settings(CURRENT_QGIS_MAJOR_VERSION="3")
    def test_non_qt6_plugin_not_in_new_qgis_ready(self):
        """
        Test that a non-Qt6 plugin does NOT appear in the new_qgis_ready endpoint.
        """
        # Log in the test user
        self.client.login(username="qt6testuser", password="testpassword")

        # Load a regular plugin (without Qt6 support)
        valid_plugin = os.path.join(TESTFILE_DIR, "valid_plugin.zip_")

        with open(valid_plugin, "rb") as file:
            uploaded_file = SimpleUploadedFile(
                "valid_plugin.zip_", file.read(), content_type="application/zip"
            )

        # Upload the non-Qt6 plugin
        response = self.client.post(
            self.upload_url,
            {
                "package": uploaded_file,
            },
        )

        # Check that the upload was successful
        self.assertEqual(response.status_code, 302)

        # Get the created plugin
        plugin = Plugin.objects.get(name="Test Plugin")
        plugin_version = PluginVersion.objects.get(plugin=plugin)

        # Approve the plugin version
        plugin_version.approved = True
        plugin_version.save()

        # Ensure the plugin is not deprecated
        plugin.deprecated = False
        plugin.save()

        # Check if this plugin has Qt6 support
        has_qt6_support = plugin_version.supports_qt6

        # Access the new_qgis_ready endpoint
        response = self.client.get(self.new_qgis_ready_url)
        plugins_in_response = response.context["object_list"]

        if has_qt6_support:
            # If the plugin has Qt6 support, it should appear
            self.assertIn(plugin, plugins_in_response)
        else:
            # If the plugin does NOT have Qt6 support, it should NOT appear
            self.assertNotIn(
                plugin,
                plugins_in_response,
                "Non-Qt6 plugin should not appear in new_qgis_ready endpoint",
            )

    def tearDown(self):
        self.client.logout()
        # Clean up any created plugins
        Plugin.objects.filter(name="Test Plugin").delete()
