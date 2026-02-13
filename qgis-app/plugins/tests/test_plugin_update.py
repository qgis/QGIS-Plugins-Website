import os
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth.models import User
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from plugins.forms import PluginVersionForm
from plugins.models import Plugin, PluginVersion


def do_nothing(*args, **kwargs):
    pass


TESTFILE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "testfiles"))


class PluginUpdateTestCase(TestCase):
    fixtures = [
        "fixtures/auth.json",
    ]

    @override_settings(MEDIA_ROOT="api/tests")
    def setUp(self):
        self.client = Client()
        self.url_upload = reverse("plugin_upload")

        # Create a test user
        self.user = User.objects.create_user(
            username="testuser", password="testpassword", email="test@example.com"
        )

        # Log in the test user
        self.client.login(username="testuser", password="testpassword")

        # Upload a plugin for renaming test.
        # This process is already tested in test_plugin_upload
        valid_plugin = os.path.join(TESTFILE_DIR, "valid_plugin.zip_")
        with open(valid_plugin, "rb") as file:
            uploaded_file = SimpleUploadedFile(
                "valid_plugin.zip_", file.read(), content_type="application/zip"
            )

        self.client.post(
            self.url_upload,
            {
                "package": uploaded_file,
            },
        )

        self.plugin = Plugin.objects.get(name="Test Plugin")

    @patch("plugins.tasks.generate_plugins_xml", new=do_nothing)
    @patch("plugins.validator._check_url_link", new=do_nothing)
    def test_plugin_new_version(self):
        """
        Test upload a new plugin version with a modified metadata
        """
        package_name = self.plugin.package_name
        self.assertEqual(self.plugin.homepage, "https://qgis.org/")
        self.assertEqual(self.plugin.tracker, "https://qgis.org/")
        self.assertEqual(self.plugin.repository, "https://qgis.org/")
        self.url_add_version = reverse("version_create", args=[package_name])

        # Test POST request without allowing name from metadata
        valid_plugin = os.path.join(TESTFILE_DIR, "change_metadata.zip_")
        with open(valid_plugin, "rb") as file:
            uploaded_file = SimpleUploadedFile(
                "change_metadata.zip_", file.read(), content_type="application/zip_"
            )

        response = self.client.post(
            self.url_add_version,
            {"package": uploaded_file, "experimental": False, "changelog": ""},
        )
        self.assertEqual(response.status_code, 302)

        # The old version should always exist when creating a new version
        self.assertTrue(
            PluginVersion.objects.filter(
                plugin__name="Test Plugin", version="0.0.1"
            ).exists()
        )
        self.assertTrue(
            PluginVersion.objects.filter(
                plugin__name="Test Plugin", version="0.0.2"
            ).exists()
        )

        self.plugin = Plugin.objects.get(name="Test Plugin")
        self.assertEqual(self.plugin.homepage, "https://github.com/")
        self.assertEqual(self.plugin.tracker, "https://github.com/")
        self.assertEqual(self.plugin.repository, "https://github.com/")

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
    def test_plugin_version_update(self):
        """
        Test update a plugin version with a modified metadata
        """
        package_name = self.plugin.package_name
        self.assertEqual(self.plugin.homepage, "https://qgis.org/")
        self.assertEqual(self.plugin.tracker, "https://qgis.org/")
        self.assertEqual(self.plugin.repository, "https://qgis.org/")
        self.url_add_version = reverse("version_update", args=[package_name, "0.0.1"])

        # Test POST request without allowing name from metadata
        valid_plugin = os.path.join(TESTFILE_DIR, "change_metadata.zip_")
        with open(valid_plugin, "rb") as file:
            uploaded_file = SimpleUploadedFile(
                "change_metadata.zip_", file.read(), content_type="application/zip_"
            )

        response = self.client.post(
            self.url_add_version,
            {"package": uploaded_file, "experimental": False, "changelog": ""},
        )
        self.assertEqual(response.status_code, 302)

        self.assertFalse(
            PluginVersion.objects.filter(
                plugin__name="Test Plugin", version="0.0.1"
            ).exists()
        )
        self.assertTrue(
            PluginVersion.objects.filter(
                plugin__name="Test Plugin", version="0.0.2"
            ).exists()
        )

        self.plugin = Plugin.objects.get(name="Test Plugin")
        self.assertEqual(self.plugin.homepage, "https://github.com/")
        self.assertEqual(self.plugin.tracker, "https://github.com/")
        self.assertEqual(self.plugin.repository, "https://github.com/")

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

    def test_plugin_version_approved_update(self):
        """
        Test update a plugin version that is already approved
        """
        package_name = self.plugin.package_name
        self.url_add_version = reverse("version_update", args=[package_name, "0.0.1"])
        version = PluginVersion.objects.get(plugin__name="Test Plugin", version="0.0.1")
        version.approved = True
        version.save()
        self.assertTrue(version.approved)

        response = self.client.get(self.url_add_version)
        # Should redirect to the plugin details page
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse("plugin_detail", args=[package_name]))

    def tearDown(self):
        self.client.logout()
