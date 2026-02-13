"""
Tests for creating empty plugins (without versions)
"""

import os
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from plugins.forms import PluginCreateForm
from plugins.models import Plugin, PluginVersion


def do_nothing(*args, **kwargs):
    pass


TESTFILE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "testfiles"))


class PluginCreateEmptyTestCase(TestCase):
    """Test creating empty plugins without versions"""

    fixtures = [
        "fixtures/auth.json",
    ]

    @override_settings(MEDIA_ROOT="api/tests")
    def setUp(self):
        self.client = Client()
        self.url = reverse("plugin_create_empty")

        # Create a test user
        self.user = User.objects.create_user(
            username="testuser",
            password="testpassword",
            email="test@example.com",
            first_name="Test",
            last_name="User",
        )

    @patch("plugins.views.plugin_notify", new=do_nothing)
    def test_create_empty_plugin_get_request(self):
        """Test GET request to create empty plugin page"""
        self.client.login(username="testuser", password="testpassword")

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response.context["form"], PluginCreateForm)
        self.assertContains(response, "Create an empty plugin")

    def test_create_empty_plugin_requires_login(self):
        """Test that anonymous users are redirected to login"""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response.url)

    @patch("plugins.views.plugin_notify", new=do_nothing)
    def test_create_empty_plugin_with_valid_data(self):
        """Test creating an empty plugin with valid data"""
        self.client.login(username="testuser", password="testpassword")

        data = {
            "package_name": "MyTestPlugin",
            "name": "My Test Plugin",
        }

        response = self.client.post(self.url, data)

        # Should redirect to token list
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Plugin.objects.filter(package_name="MyTestPlugin").exists())

        plugin = Plugin.objects.get(package_name="MyTestPlugin")
        self.assertEqual(plugin.name, "My Test Plugin")
        self.assertEqual(plugin.created_by, self.user)
        self.assertEqual(plugin.author, "Test User")
        self.assertEqual(plugin.email, "test@example.com")
        self.assertIn("Placeholder", plugin.description)

        # Should have no versions yet
        self.assertEqual(plugin.pluginversion_set.count(), 0)

        # Should redirect to plugin detail page
        expected_url = reverse("plugin_detail", args=[plugin.package_name])
        self.assertRedirects(response, expected_url)

    @patch("plugins.views.plugin_notify", new=do_nothing)
    def test_create_empty_plugin_invalid_package_name_characters(self):
        """Test that invalid package_name characters are rejected"""
        self.client.login(username="testuser", password="testpassword")

        invalid_names = [
            "my plugin",  # spaces
            "my/plugin",  # slash
            "my.plugin",  # dot
            "my@plugin",  # special char
            "123plugin",  # starts with digit
            "_myplugin",  # starts with underscore
        ]

        for invalid_name in invalid_names:
            data = {
                "package_name": invalid_name,
                "name": "My Test Plugin",
            }

            response = self.client.post(self.url, data)
            self.assertEqual(response.status_code, 200)  # Form error, not redirect
            self.assertFalse(Plugin.objects.filter(package_name=invalid_name).exists())
            self.assertFormError(
                response,
                "form",
                "package_name",
                "Package name must start with a letter and can contain only ASCII letters, digits, '-' or '_'.",
            )

    @patch("plugins.views.plugin_notify", new=do_nothing)
    def test_create_empty_plugin_valid_package_name_characters(self):
        """Test that valid package_name characters are accepted"""
        self.client.login(username="testuser", password="testpassword")

        valid_names = [
            ("MyPlugin", "My Test Plugin One"),
            ("my_plugin", "My Test Plugin Two"),
            ("my-plugin", "My Test Plugin Three"),
            ("MyPlugin123", "My Test Plugin Four"),
        ]

        for valid_name, plugin_name in valid_names:
            data = {
                "package_name": valid_name,
                "name": plugin_name,
            }

            response = self.client.post(self.url, data)
            self.assertEqual(response.status_code, 302)  # Successful redirect
            self.assertTrue(Plugin.objects.filter(package_name=valid_name).exists())

    @patch("plugins.views.plugin_notify", new=do_nothing)
    def test_create_empty_plugin_duplicate_package_name(self):
        """Test that duplicate package_name is rejected (case-insensitive)"""
        self.client.login(username="testuser", password="testpassword")

        # Create first plugin
        data = {
            "package_name": "MyPlugin",
            "name": "My First Plugin",
        }
        response = self.client.post(self.url, data)
        self.assertEqual(response.status_code, 302)

        # Try to create with same package_name (different case)
        data = {
            "package_name": "myplugin",  # lowercase
            "name": "My Second Plugin",
        }
        response = self.client.post(self.url, data)
        self.assertEqual(response.status_code, 200)  # Form error
        self.assertFormError(
            response,
            "form",
            "package_name",
            "A plugin with a similar package name (MyPlugin) already exists.",
        )

        # Should still only have one plugin
        self.assertEqual(
            Plugin.objects.filter(package_name__iexact="myplugin").count(), 1
        )

    @patch("plugins.views.plugin_notify", new=do_nothing)
    def test_create_empty_plugin_duplicate_name(self):
        """Test that duplicate name is rejected (case-insensitive)"""
        self.client.login(username="testuser", password="testpassword")

        # Create first plugin
        data = {
            "package_name": "MyPlugin1",
            "name": "My Awesome Plugin",
        }
        response = self.client.post(self.url, data)
        self.assertEqual(response.status_code, 302)

        # Try to create with same name (different case)
        data = {
            "package_name": "MyPlugin2",
            "name": "my awesome plugin",  # different case
        }
        response = self.client.post(self.url, data)
        self.assertEqual(response.status_code, 200)  # Form error
        self.assertFormError(
            response,
            "form",
            "name",
            "A plugin with a similar name (My Awesome Plugin) already exists.",
        )

        # Should still only have one plugin with that name
        self.assertEqual(
            Plugin.objects.filter(name__iexact="my awesome plugin").count(), 1
        )

    @patch("plugins.views.plugin_notify", new=do_nothing)
    @patch("plugins.tasks.generate_plugins_xml", new=do_nothing)
    @patch("plugins.validator._check_url_link", new=do_nothing)
    @patch("plugins.security_utils.run_security_scan", new=do_nothing)
    def test_upload_version_after_creating_empty_plugin(self):
        """Test that a version can be uploaded after creating an empty plugin"""
        self.client.login(username="testuser", password="testpassword")

        # Create empty plugin
        data = {
            "package_name": "test_modul",
            "name": "Test Module Plugin",
        }
        response = self.client.post(self.url, data)
        self.assertEqual(response.status_code, 302)

        plugin = Plugin.objects.get(package_name="test_modul")
        self.assertEqual(plugin.pluginversion_set.count(), 0)

        # Now upload a version
        valid_plugin = os.path.join(TESTFILE_DIR, "valid_plugin.zip_")
        with open(valid_plugin, "rb") as file:
            uploaded_file = SimpleUploadedFile(
                "valid_plugin.zip_", file.read(), content_type="application/zip"
            )

        upload_url = reverse("version_create", args=[plugin.package_name])
        response = self.client.post(
            upload_url,
            {
                "package": uploaded_file,
            },
        )

        self.assertEqual(response.status_code, 302)

        # Plugin should now have one version
        plugin.refresh_from_db()
        self.assertEqual(plugin.pluginversion_set.count(), 1)

        version = plugin.pluginversion_set.first()
        self.assertEqual(version.version, "0.0.1")

        # Metadata should be updated from the package
        self.assertNotIn("Placeholder", plugin.description)

    @patch("plugins.views.plugin_notify", new=do_nothing)
    def test_create_empty_plugin_user_without_email(self):
        """Test creating plugin when user has no email"""
        # Create user without email
        user_no_email = User.objects.create_user(
            username="noemail", password="testpassword"
        )
        self.client.login(username="noemail", password="testpassword")

        data = {
            "package_name": "NoEmailPlugin",
            "name": "No Email Plugin",
        }

        response = self.client.post(self.url, data)
        self.assertEqual(response.status_code, 302)

        plugin = Plugin.objects.get(package_name="NoEmailPlugin")
        # Should have a default email
        self.assertEqual(plugin.email, "noreply@example.com")

    @patch("plugins.views.plugin_notify", new=do_nothing)
    def test_create_empty_plugin_user_without_full_name(self):
        """Test creating plugin when user has no first/last name"""
        # Create user without first/last name
        user_no_name = User.objects.create_user(
            username="noname", password="testpassword", email="test@example.com"
        )
        self.client.login(username="noname", password="testpassword")

        data = {
            "package_name": "NoNamePlugin",
            "name": "No Name Plugin",
        }

        response = self.client.post(self.url, data)
        self.assertEqual(response.status_code, 302)

        plugin = Plugin.objects.get(package_name="NoNamePlugin")
        # Should use username as author
        self.assertEqual(plugin.author, "noname")

    def tearDown(self):
        self.client.logout()
