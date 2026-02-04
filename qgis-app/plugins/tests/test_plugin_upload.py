import os
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth.models import User
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from plugins.forms import PackageUploadForm
from plugins.models import Plugin, PluginVersion


def do_nothing(*args, **kwargs):
    pass


TESTFILE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "testfiles"))


class PluginUploadTestCase(TestCase):
    fixtures = [
        "fixtures/auth.json",
    ]

    @override_settings(MEDIA_ROOT="api/tests")
    def setUp(self):
        self.client = Client()
        self.url = reverse("plugin_upload")

        # Create a test user
        self.user = User.objects.create_user(
            username="testuser", password="testpassword", email="test@example.com"
        )

    @patch("plugins.tasks.generate_plugins_xml", new=do_nothing)
    @patch("plugins.validator._check_url_link", new=do_nothing)
    def test_plugin_upload_form(self):
        # Log in the test user
        self.client.login(username="testuser", password="testpassword")

        # Test GET request
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response.context["form"], PackageUploadForm)

        # Test POST request with invalid form data
        response = self.client.post(self.url, {})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["form"].is_valid())

        valid_plugin = os.path.join(TESTFILE_DIR, "valid_plugin.zip_")
        with open(valid_plugin, "rb") as file:
            uploaded_file = SimpleUploadedFile(
                "valid_plugin.zip_", file.read(), content_type="application/zip"
            )

        # Test POST request with valid form data
        response = self.client.post(
            self.url,
            {
                "package": uploaded_file,
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(Plugin.objects.filter(name="Test Plugin").exists())
        self.assertEqual(
            Plugin.objects.get(name="Test Plugin")
            .tags.filter(name__in=["python", "example", "test"])
            .count(),
            3,
        )
        self.assertTrue(
            PluginVersion.objects.filter(
                plugin__name="Test Plugin", version="0.0.1"
            ).exists()
        )

        self.assertIn(
            "staff.recipient@example.com",
            mail.outbox[0].recipients(),
        )

        self.assertNotIn(
            "admin@admin.it",
            mail.outbox[0].recipients(),
        )
        self.assertNotIn("staff@staff.it", mail.outbox[0].recipients())

        # Should use the new email
        self.assertEqual(mail.outbox[0].from_email, settings.DEFAULT_FROM_EMAIL)

    @patch("plugins.tasks.generate_plugins_xml", new=do_nothing)
    @patch("plugins.validator._check_url_link", new=do_nothing)
    def test_plugin_upload_without_screenshot(self):
        """Test that plugin upload works correctly without screenshot"""
        self.client.login(username="testuser", password="testpassword")

        valid_plugin = os.path.join(TESTFILE_DIR, "valid_plugin.zip_")
        with open(valid_plugin, "rb") as file:
            uploaded_file = SimpleUploadedFile(
                "valid_plugin.zip_", file.read(), content_type="application/zip"
            )

        response = self.client.post(
            self.url,
            {
                "package": uploaded_file,
            },
        )

        self.assertEqual(response.status_code, 302)
        plugin = Plugin.objects.get(name="Test Plugin")

        # Plugin should be created successfully
        self.assertTrue(plugin)
        # Screenshot should be empty/null
        self.assertFalse(plugin.screenshot)

        # Version should also have no screenshot
        version = PluginVersion.objects.get(plugin=plugin, version="0.0.1")
        self.assertFalse(version.screenshot)

    @patch("plugins.tasks.generate_plugins_xml", new=do_nothing)
    @patch("plugins.validator._check_url_link", new=do_nothing)
    def test_plugin_upload_with_screenshot_updates_both_levels(self):
        """Test that uploading plugin with screenshot updates both plugin and version"""
        self.client.login(username="testuser", password="testpassword")

        plugin_with_screenshot = os.path.join(
            TESTFILE_DIR, "plugin_with_screenshot.zip_"
        )
        with open(plugin_with_screenshot, "rb") as file:
            uploaded_file = SimpleUploadedFile(
                "plugin_with_screenshot.zip_",
                file.read(),
                content_type="application/zip",
            )

        response = self.client.post(
            self.url,
            {
                "package": uploaded_file,
            },
        )

        self.assertEqual(response.status_code, 302)
        plugin = Plugin.objects.get(name="Test Plugin")
        version = PluginVersion.objects.get(plugin=plugin, version="0.0.1")

        # 1. Version.screenshot is saved (historical record)
        self.assertTrue(version.screenshot)
        self.assertIn("preview", version.screenshot.name)

        # 2. Plugin.screenshot is saved (for display)
        self.assertTrue(plugin.screenshot)
        self.assertIn("preview", plugin.screenshot.name)

        # 3. Both should reference the same type of file
        self.assertTrue(version.screenshot.name.endswith(".png"))
        self.assertTrue(plugin.screenshot.name.endswith(".png"))

    def tearDown(self):
        self.client.logout()
