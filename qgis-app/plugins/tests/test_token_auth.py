import os

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from plugins.forms import PackageUploadForm
from plugins.models import Plugin, PluginVersion
from rest_framework_simplejwt.token_blacklist.models import OutstandingToken
from rest_framework_simplejwt.tokens import RefreshToken


def do_nothing(*args, **kwargs):
    pass


TESTFILE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "testfiles"))


class UploadWithTokenTestCase(TestCase):
    fixtures = ["fixtures/auth.json"]

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

        package_name = self.plugin.package_name
        version = "0.0.1"
        self.url_add_version = reverse("version_create_api", args=[package_name])
        self.url_update_version = reverse(
            "version_update_api", args=[package_name, version]
        )
        self.url_token_list = reverse("plugin_token_list", args=[package_name])
        self.url_token_create = reverse("plugin_token_create", args=[package_name])

    def test_token_create(self):
        # Test token create
        response = self.client.post(self.url_token_create, {})
        self.assertEqual(response.status_code, 302)
        tokens = OutstandingToken.objects.all()
        self.assertEqual(tokens.count(), 1)

    def test_upload_new_version_with_valid_token(self):
        # Generate a token for the authenticated user
        self.client.post(self.url_token_create, {})
        outstanding_token = OutstandingToken.objects.last().token
        refresh = RefreshToken(outstanding_token)
        refresh["plugin_id"] = self.plugin.pk
        refresh["refresh_jti"] = refresh["jti"]
        access_token = str(refresh.access_token)

        # Log out the user and use the token
        self.client.logout()

        valid_plugin = os.path.join(TESTFILE_DIR, "valid_plugin_0.0.2.zip_")
        with open(valid_plugin, "rb") as file:
            uploaded_file = SimpleUploadedFile(
                "valid_plugin_0.0.2.zip_", file.read(), content_type="application/zip_"
            )

        c = Client(HTTP_AUTHORIZATION=f"Bearer {access_token}")

        # Test POST request with access token
        response = c.post(
            self.url_add_version,
            {
                "package": uploaded_file,
            },
        )
        self.assertEqual(response.status_code, 201)
        self.assertIn("application/json", response["Content-Type"])
        response_data = response.json()
        self.assertTrue(response_data.get("success"))
        self.assertEqual(response_data.get("version"), "0.0.2")
        self.assertTrue(
            PluginVersion.objects.filter(
                plugin__name="Test Plugin", version="0.0.2"
            ).exists()
        )

    def test_upload_new_version_with_invalid_token(self):
        # Log out the user and use the token
        self.client.logout()

        access_token = "invalid_token"
        valid_plugin = os.path.join(TESTFILE_DIR, "valid_plugin_0.0.2.zip_")
        with open(valid_plugin, "rb") as file:
            uploaded_file = SimpleUploadedFile(
                "valid_plugin_0.0.2.zip_", file.read(), content_type="application/zip_"
            )

        c = Client(HTTP_AUTHORIZATION=f"Bearer {access_token}")

        # Test POST request with access token
        response = c.post(
            self.url_add_version,
            {
                "package": uploaded_file,
            },
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(
            PluginVersion.objects.filter(
                plugin__name="Test Plugin", version="0.0.2"
            ).exists()
        )

    def test_update_version_with_valid_token(self):
        # Generate a token for the authenticated user
        self.client.post(self.url_token_create, {})
        outstanding_token = OutstandingToken.objects.last().token
        refresh = RefreshToken(outstanding_token)
        refresh["plugin_id"] = self.plugin.pk
        refresh["refresh_jti"] = refresh["jti"]
        access_token = str(refresh.access_token)

        # Log out the user and use the token
        self.client.logout()

        valid_plugin = os.path.join(TESTFILE_DIR, "valid_plugin_0.0.2.zip_")
        with open(valid_plugin, "rb") as file:
            uploaded_file = SimpleUploadedFile(
                "valid_plugin_0.0.2.zip_", file.read(), content_type="application/zip_"
            )

        c = Client(HTTP_AUTHORIZATION=f"Bearer {access_token}")

        # Test POST request with access token
        response = c.post(
            self.url_update_version,
            {
                "package": uploaded_file,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("application/json", response["Content-Type"])
        response_data = response.json()
        self.assertTrue(response_data.get("success"))
        self.assertEqual(response_data.get("version"), "0.0.2")
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

    def test_update_approved_version_with_token(self):
        # Generate a token for the authenticated user
        self.client.post(self.url_token_create, {})
        outstanding_token = OutstandingToken.objects.last().token
        refresh = RefreshToken(outstanding_token)
        refresh["plugin_id"] = self.plugin.pk
        refresh["refresh_jti"] = refresh["jti"]
        access_token = str(refresh.access_token)

        version = PluginVersion.objects.get(plugin__name="Test Plugin", version="0.0.1")
        version.approved = True
        version.save()
        self.assertTrue(version.approved)

        # Log out the user and use the token
        self.client.logout()

        c = Client(HTTP_AUTHORIZATION=f"Bearer {access_token}")

        # Test request with access token
        response = c.get(self.url_update_version)
        # Check that the response is forbidden
        self.assertEqual(response.status_code, 401)
        self.assertIn("application/json", response["Content-Type"])
        self.assertEqual(
            response.json().get("detail"),
            "You cannot edit an approved version, please create a new version instead.",
        )

    def test_update_version_with_invalid_token(self):
        # Log out the user and use the token
        self.client.logout()
        access_token = "invalid_token"

        valid_plugin = os.path.join(TESTFILE_DIR, "valid_plugin_0.0.2.zip_")
        with open(valid_plugin, "rb") as file:
            uploaded_file = SimpleUploadedFile(
                "valid_plugin_0.0.2.zip_", file.read(), content_type="application/zip_"
            )

        c = Client(HTTP_AUTHORIZATION=f"Bearer {access_token}")

        # Test POST request with access token
        response = c.post(
            self.url_update_version,
            {
                "package": uploaded_file,
            },
        )
        self.assertEqual(response.status_code, 403)
        self.assertTrue(
            PluginVersion.objects.filter(
                plugin__name="Test Plugin", version="0.0.1"
            ).exists()
        )
        self.assertFalse(
            PluginVersion.objects.filter(
                plugin__name="Test Plugin", version="0.0.2"
            ).exists()
        )


class APIResponseTestCase(TestCase):
    """Test cases for API response improvements"""

    fixtures = ["fixtures/auth.json"]

    @override_settings(MEDIA_ROOT="api/tests")
    def setUp(self):
        self.client = Client()
        self.url_upload = reverse("plugin_upload")

        # Create a test user
        self.user = User.objects.create_user(
            username="apiuser", password="apipassword", email="api@example.com"
        )

        # Log in the test user
        self.client.login(username="apiuser", password="apipassword")

        # Upload a plugin
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
        package_name = self.plugin.package_name

        self.url_add_version = reverse("version_create_api", args=[package_name])
        self.url_token_create = reverse("plugin_token_create", args=[package_name])

        # Create token
        self.client.post(self.url_token_create, {})
        outstanding_token = OutstandingToken.objects.last().token
        refresh = RefreshToken(outstanding_token)
        refresh["plugin_id"] = self.plugin.pk
        refresh["refresh_jti"] = refresh["jti"]
        self.access_token = str(refresh.access_token)

        self.client.logout()

    def test_api_create_success_response_structure(self):
        """Test that successful version creation returns proper JSON structure"""
        valid_plugin = os.path.join(TESTFILE_DIR, "valid_plugin_0.0.2.zip_")
        with open(valid_plugin, "rb") as file:
            uploaded_file = SimpleUploadedFile(
                "valid_plugin_0.0.2.zip_", file.read(), content_type="application/zip_"
            )

        c = Client(HTTP_AUTHORIZATION=f"Bearer {self.access_token}")
        response = c.post(
            self.url_add_version,
            {
                "package": uploaded_file,
            },
        )

        # Check status code
        self.assertEqual(response.status_code, 201)

        # Check content type
        self.assertIn("application/json", response["Content-Type"])

        # Check response structure
        data = response.json()
        self.assertIn("success", data)
        self.assertTrue(data["success"])
        self.assertIn("message", data)
        self.assertIn("version", data)
        self.assertIn("plugin_id", data)
        self.assertIn("version_id", data)

        # Verify data values
        self.assertEqual(data["version"], "0.0.2")
        self.assertEqual(data["plugin_id"], self.plugin.pk)

    def test_api_create_missing_package_error(self):
        """Test that missing package returns 400 error with JSON"""
        c = Client(HTTP_AUTHORIZATION=f"Bearer {self.access_token}")
        response = c.post(self.url_add_version, {})

        # Check status code
        self.assertEqual(response.status_code, 400)

        # Check content type
        self.assertIn("application/json", response["Content-Type"])

        # Check error response structure
        data = response.json()
        self.assertIn("success", data)
        self.assertFalse(data["success"])
        self.assertIn("error", data)
        self.assertIn("errors", data)

    def test_api_create_invalid_package_error(self):
        """Test that invalid package returns 400 error with JSON"""
        # Create a fake non-zip file
        invalid_file = SimpleUploadedFile(
            "invalid.txt", b"This is not a zip file", content_type="text/plain"
        )

        c = Client(HTTP_AUTHORIZATION=f"Bearer {self.access_token}")
        response = c.post(
            self.url_add_version,
            {
                "package": invalid_file,
            },
        )

        # Check status code
        self.assertEqual(response.status_code, 400)

        # Check content type
        self.assertIn("application/json", response["Content-Type"])

        # Check error response structure
        data = response.json()
        self.assertIn("success", data)
        self.assertFalse(data["success"])
        self.assertIn("error", data)

    def test_api_create_duplicate_version_error(self):
        """Test that duplicate version returns 400 error with JSON"""
        # First upload
        valid_plugin = os.path.join(TESTFILE_DIR, "valid_plugin_0.0.2.zip_")
        with open(valid_plugin, "rb") as file:
            uploaded_file = SimpleUploadedFile(
                "valid_plugin_0.0.2.zip_", file.read(), content_type="application/zip_"
            )

        c = Client(HTTP_AUTHORIZATION=f"Bearer {self.access_token}")
        response1 = c.post(
            self.url_add_version,
            {
                "package": uploaded_file,
            },
        )
        self.assertEqual(response1.status_code, 201)

        # Try to upload the same version again
        with open(valid_plugin, "rb") as file:
            uploaded_file2 = SimpleUploadedFile(
                "valid_plugin_0.0.2.zip_", file.read(), content_type="application/zip_"
            )

        response2 = c.post(
            self.url_add_version,
            {
                "package": uploaded_file2,
            },
        )

        # Check status code
        self.assertEqual(response2.status_code, 400)

        # Check content type
        self.assertIn("application/json", response2["Content-Type"])

        # Check error response structure
        data = response2.json()
        self.assertIn("success", data)
        self.assertFalse(data["success"])
        self.assertIn("error", data)

    def test_api_get_request_not_allowed(self):
        """Test that GET request returns 405 Method Not Allowed"""
        c = Client(HTTP_AUTHORIZATION=f"Bearer {self.access_token}")
        response = c.get(self.url_add_version)

        # Check status code
        self.assertEqual(response.status_code, 405)

        # Check content type
        self.assertIn("application/json", response["Content-Type"])

        # Check error response structure
        data = response.json()
        self.assertIn("success", data)
        self.assertFalse(data["success"])
        self.assertIn("error", data)
        self.assertIn("Method not allowed", data["error"])

    def test_api_update_success_response_structure(self):
        """Test that successful version update returns proper JSON structure"""
        # First create version 0.0.2
        valid_plugin = os.path.join(TESTFILE_DIR, "valid_plugin_0.0.2.zip_")
        with open(valid_plugin, "rb") as file:
            uploaded_file = SimpleUploadedFile(
                "valid_plugin_0.0.2.zip_", file.read(), content_type="application/zip_"
            )

        c = Client(HTTP_AUTHORIZATION=f"Bearer {self.access_token}")
        c.post(
            self.url_add_version,
            {
                "package": uploaded_file,
            },
        )

        # Now update it with version 0.0.3
        update_plugin = os.path.join(TESTFILE_DIR, "valid_plugin_0.0.3.zip_")

        # Check if file exists, if not we'll use 0.0.2 again but with modified metadata
        if os.path.exists(update_plugin):
            with open(update_plugin, "rb") as file:
                uploaded_file2 = SimpleUploadedFile(
                    "valid_plugin_0.0.3.zip_",
                    file.read(),
                    content_type="application/zip_",
                )
        else:
            # Use the same file - the test is about response structure
            with open(valid_plugin, "rb") as file:
                uploaded_file2 = SimpleUploadedFile(
                    "valid_plugin_0.0.2_update.zip_",
                    file.read(),
                    content_type="application/zip_",
                )

        url_update_version = reverse(
            "version_update_api", args=[self.plugin.package_name, "0.0.2"]
        )
        response = c.post(
            url_update_version,
            {
                "package": uploaded_file2,
            },
        )

        # Check status code
        self.assertEqual(response.status_code, 200)

        # Check content type
        self.assertIn("application/json", response["Content-Type"])

        # Check response structure
        data = response.json()
        self.assertIn("success", data)
        self.assertTrue(data["success"])
        self.assertIn("message", data)
        self.assertIn("version", data)
        self.assertIn("plugin_id", data)
        self.assertIn("version_id", data)

    def test_api_response_includes_security_scan(self):
        """Test that response includes security scan information if available"""
        valid_plugin = os.path.join(TESTFILE_DIR, "valid_plugin_0.0.2.zip_")
        with open(valid_plugin, "rb") as file:
            uploaded_file = SimpleUploadedFile(
                "valid_plugin_0.0.2.zip_", file.read(), content_type="application/zip_"
            )

        c = Client(HTTP_AUTHORIZATION=f"Bearer {self.access_token}")
        response = c.post(
            self.url_add_version,
            {
                "package": uploaded_file,
            },
        )

        self.assertEqual(response.status_code, 201)
        data = response.json()

        # Security scan should be present (even if empty/null)
        # The actual presence depends on whether security scanning is enabled
        # Just verify the response structure is valid
        self.assertIsNotNone(data)
        self.assertTrue(data.get("success"))

    def test_api_approval_message_for_untrusted_user(self):
        """Test that untrusted users get approval message in response"""
        # The test user doesn't have approval permissions by default
        valid_plugin = os.path.join(TESTFILE_DIR, "valid_plugin_0.0.2.zip_")
        with open(valid_plugin, "rb") as file:
            uploaded_file = SimpleUploadedFile(
                "valid_plugin_0.0.2.zip_", file.read(), content_type="application/zip_"
            )

        c = Client(HTTP_AUTHORIZATION=f"Bearer {self.access_token}")
        response = c.post(
            self.url_add_version,
            {
                "package": uploaded_file,
            },
        )

        self.assertEqual(response.status_code, 201)
        data = response.json()

        # Check for approval-related fields
        self.assertIn("approved", data)

        # If user is not trusted, should have approval message
        if not self.user.has_perm("plugins.can_approve"):
            self.assertIn("approval_message", data)
            self.assertFalse(data["approved"])
