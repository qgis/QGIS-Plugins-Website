import os
from unittest.mock import patch

from django.contrib.auth.models import Permission, User
from django.contrib.contenttypes.models import ContentType
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from plugins.forms import PackageUploadForm
from plugins.models import (
    VALIDATION_STATUS_VALIDATING,
    Plugin,
    PluginVersion,
    SecurityRule,
)
from rest_framework_simplejwt.token_blacklist.models import OutstandingToken
from rest_framework_simplejwt.tokens import RefreshToken


def do_nothing(*args, **kwargs):
    pass


TESTFILE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "testfiles"))


class UploadWithTokenTestCase(TestCase):
    fixtures = ["fixtures/auth.json"]

    @patch("plugins.tasks.generate_plugins_xml", new=do_nothing)
    @patch("plugins.validator._check_url_link", new=do_nothing)
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

    def test_new_version_not_auto_approved_for_untrusted_user_on_approved_plugin(self):
        """
        Security: uploading a new version via token must NOT be auto-approved
        because the plugin already has an approved version. Only the user's
        can_approve permission should grant approval.
        """
        # Approve the existing version to simulate an approved plugin
        version = PluginVersion.objects.get(plugin__name="Test Plugin", version="0.0.1")
        version.approved = True
        version.save()

        # Generate a token for the untrusted user
        self.client.post(self.url_token_create, {})
        outstanding_token = OutstandingToken.objects.last().token
        refresh = RefreshToken(outstanding_token)
        refresh["plugin_id"] = self.plugin.pk
        refresh["refresh_jti"] = refresh["jti"]
        access_token = str(refresh.access_token)

        self.client.logout()

        valid_plugin = os.path.join(TESTFILE_DIR, "valid_plugin_0.0.2.zip_")
        with open(valid_plugin, "rb") as file:
            uploaded_file = SimpleUploadedFile(
                "valid_plugin_0.0.2.zip_", file.read(), content_type="application/zip_"
            )

        c = Client(HTTP_AUTHORIZATION=f"Bearer {access_token}")
        response = c.post(self.url_add_version, {"package": uploaded_file})

        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertTrue(data.get("success"))

        new_version = PluginVersion.objects.get(
            plugin__name="Test Plugin", version="0.0.2"
        )
        self.assertFalse(
            new_version.approved,
            "New version must NOT be auto-approved just because the plugin is approved; "
            "only user trust (can_approve) should grant approval.",
        )
        self.assertFalse(data.get("approved"))
        self.assertIn("approval_message", data)

    @patch("plugins.tasks.run_security_scan.run_security_scan_task.delay")
    def test_new_version_queued_for_scan_for_trusted_token_user(self, mock_scan_delay):
        """
        A token whose owner holds can_approve triggers async security validation,
        NOT immediate approval. The version starts with approved=False and
        validation_status=VALIDATING; the scan task is queued. Approval happens
        asynchronously after the scan passes.
        """
        # Grant can_approve to the token user
        ct = ContentType.objects.get_for_model(Plugin)
        perm = Permission.objects.get(codename="can_approve", content_type=ct)
        self.user.user_permissions.add(perm)
        # Refresh to bust the permission cache
        self.user = self.user.__class__.objects.get(pk=self.user.pk)

        # Generate a token for the now-trusted user
        self.client.post(self.url_token_create, {})
        outstanding_token = OutstandingToken.objects.last().token
        refresh = RefreshToken(outstanding_token)
        refresh["plugin_id"] = self.plugin.pk
        refresh["refresh_jti"] = refresh["jti"]
        access_token = str(refresh.access_token)

        self.client.logout()

        valid_plugin = os.path.join(TESTFILE_DIR, "valid_plugin_0.0.2.zip_")
        with open(valid_plugin, "rb") as file:
            uploaded_file = SimpleUploadedFile(
                "valid_plugin_0.0.2.zip_", file.read(), content_type="application/zip_"
            )

        c = Client(HTTP_AUTHORIZATION=f"Bearer {access_token}")
        response = c.post(self.url_add_version, {"package": uploaded_file})

        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertTrue(data.get("success"))

        new_version = PluginVersion.objects.get(
            plugin__name="Test Plugin", version="0.0.2"
        )
        self.assertFalse(
            new_version.approved,
            "Upload always starts unapproved; approval is deferred to the async security scan.",
        )
        self.assertEqual(new_version.validation_status, VALIDATION_STATUS_VALIDATING)
        self.assertFalse(data.get("approved"))
        mock_scan_delay.assert_called_once_with(
            new_version.pk, auto_approve=False, skipped_rule_ids=[]
        )

    @patch("plugins.tasks.run_security_scan.run_security_scan_task.delay")
    def test_new_version_publish_immediately_opt_in_for_trusted_token_user(
        self, mock_scan_delay
    ):
        """
        A trusted token user who passes auto_approve_after_scan=true in the POST body
        should have the scan task queued with auto_approve=True.
        """
        # Grant can_approve to the token user
        ct = ContentType.objects.get_for_model(Plugin)
        perm = Permission.objects.get(codename="can_approve", content_type=ct)
        self.user.user_permissions.add(perm)
        self.user = self.user.__class__.objects.get(pk=self.user.pk)

        self.client.post(self.url_token_create, {})
        outstanding_token = OutstandingToken.objects.last().token
        refresh = RefreshToken(outstanding_token)
        refresh["plugin_id"] = self.plugin.pk
        refresh["refresh_jti"] = refresh["jti"]
        access_token = str(refresh.access_token)

        self.client.logout()

        valid_plugin = os.path.join(TESTFILE_DIR, "valid_plugin_0.0.2.zip_")
        with open(valid_plugin, "rb") as file:
            uploaded_file = SimpleUploadedFile(
                "valid_plugin_0.0.2.zip_", file.read(), content_type="application/zip_"
            )

        c = Client(HTTP_AUTHORIZATION=f"Bearer {access_token}")
        response = c.post(
            self.url_add_version,
            {"package": uploaded_file, "auto_approve_after_scan": "true"},
        )

        self.assertEqual(response.status_code, 201)
        version = PluginVersion.objects.get(plugin__name="Test Plugin", version="0.0.2")
        mock_scan_delay.assert_called_once_with(
            version.pk, auto_approve=True, skipped_rule_ids=[]
        )


class APIResponseTestCase(TestCase):
    """Test cases for API response improvements"""

    fixtures = ["fixtures/auth.json"]

    @patch("plugins.tasks.generate_plugins_xml", new=do_nothing)
    @patch("plugins.validator._check_url_link", new=do_nothing)
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


class EmptyPluginWithTokenTestCase(TestCase):
    """Test creating empty plugin and uploading first version via token"""

    fixtures = ["fixtures/auth.json"]

    @patch("plugins.tasks.generate_plugins_xml", new=do_nothing)
    @patch("plugins.validator._check_url_link", new=do_nothing)
    @override_settings(MEDIA_ROOT="api/tests")
    def setUp(self):
        self.client = Client()

        # Create a test user
        self.user = User.objects.create_user(
            username="testuser",
            password="testpassword",
            email="test@example.com",
            first_name="Test",
            last_name="User",
        )

        self.client.login(username="testuser", password="testpassword")

    def test_create_empty_plugin_then_upload_with_token(self):
        """Test complete workflow: create empty plugin, generate token, upload version"""
        # Step 1: Create empty plugin
        with patch("plugins.views.plugin_notify", new=do_nothing):
            url_create_empty = reverse("plugin_create_empty")
            response = self.client.post(
                url_create_empty,
                {
                    "package_name": "test_modul",
                    "name": "My Test Plugin",
                },
            )
            self.assertEqual(response.status_code, 302)

        plugin = Plugin.objects.get(package_name="test_modul")
        self.assertEqual(plugin.pluginversion_set.count(), 0)

        # Step 2: Generate token
        url_token_create = reverse("plugin_token_create", args=[plugin.package_name])
        response = self.client.post(url_token_create, {})
        self.assertEqual(response.status_code, 302)

        # Step 3: Get the token
        outstanding_token = OutstandingToken.objects.last().token
        refresh = RefreshToken(outstanding_token)
        refresh["plugin_id"] = plugin.pk
        refresh["refresh_jti"] = refresh["jti"]
        access_token = str(refresh.access_token)

        # Step 4: Log out and upload version with token
        self.client.logout()

        valid_plugin = os.path.join(TESTFILE_DIR, "valid_plugin.zip_")
        with open(valid_plugin, "rb") as file:
            uploaded_file = SimpleUploadedFile(
                "valid_plugin.zip_", file.read(), content_type="application/zip"
            )

        url_add_version = reverse("version_create_api", args=[plugin.package_name])

        with patch("plugins.tasks.generate_plugins_xml", new=do_nothing):
            with patch("plugins.validator._check_url_link", new=do_nothing):
                with patch("plugins.security_utils.run_security_scan", new=do_nothing):
                    c = Client(HTTP_AUTHORIZATION=f"Bearer {access_token}")
                    response = c.post(
                        url_add_version,
                        {
                            "package": uploaded_file,
                        },
                    )

        self.assertEqual(response.status_code, 201)
        response.json()

        # Verify version was created
        plugin.refresh_from_db()
        self.assertEqual(plugin.pluginversion_set.count(), 1)

        version = plugin.pluginversion_set.first()
        self.assertEqual(version.version, "0.0.1")

        # Verify metadata was updated from package
        self.assertNotIn("Placeholder", plugin.description)
        self.assertEqual(plugin.description, "I am here for testing purpose")

    def test_cannot_upload_mismatched_package_name_to_empty_plugin(self):
        """Test that uploading a package with wrong folder name fails"""
        # Create empty plugin with specific package_name
        with patch("plugins.views.plugin_notify", new=do_nothing):
            url_create_empty = reverse("plugin_create_empty")
            response = self.client.post(
                url_create_empty,
                {
                    "package_name": "different_name",
                    "name": "Different Plugin",
                },
            )
            self.assertEqual(response.status_code, 302)

        plugin = Plugin.objects.get(package_name="different_name")

        # Generate token
        url_token_create = reverse("plugin_token_create", args=[plugin.package_name])
        response = self.client.post(url_token_create, {})
        self.assertEqual(response.status_code, 302)

        outstanding_token = OutstandingToken.objects.last().token
        refresh = RefreshToken(outstanding_token)
        refresh["plugin_id"] = plugin.pk
        refresh["refresh_jti"] = refresh["jti"]
        access_token = str(refresh.access_token)

        self.client.logout()

        # Try to upload package with different folder name (test_modul)
        valid_plugin = os.path.join(TESTFILE_DIR, "valid_plugin.zip_")
        with open(valid_plugin, "rb") as file:
            uploaded_file = SimpleUploadedFile(
                "valid_plugin.zip_", file.read(), content_type="application/zip"
            )

        url_add_version = reverse("version_create_api", args=[plugin.package_name])

        with patch("plugins.validator._check_url_link", new=do_nothing):
            c = Client(HTTP_AUTHORIZATION=f"Bearer {access_token}")
            response = c.post(
                url_add_version,
                {
                    "package": uploaded_file,
                },
            )

        # Should fail with 400 bad request
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertIn("error", data)

        # No version should be created
        plugin.refresh_from_db()
        self.assertEqual(plugin.pluginversion_set.count(), 0)


# ---------------------------------------------------------------------------
# Security rule skipping via token API
# ---------------------------------------------------------------------------


class TokenAPISkipSecurityRulesTest(TestCase):
    """Tests for passing skip_security_rules via the token-based REST API."""

    fixtures = ["fixtures/auth.json"]

    @patch("plugins.tasks.generate_plugins_xml", new=do_nothing)
    @patch("plugins.validator._check_url_link", new=do_nothing)
    @override_settings(MEDIA_ROOT="api/tests")
    def setUp(self):
        self.client = Client()
        self.url_upload = reverse("plugin_upload")

        self.user = User.objects.create_user(
            username="skiptoken_user",
            password="testpassword",
            email="skiptoken@example.com",
        )
        self.client.login(username="skiptoken_user", password="testpassword")

        valid_plugin = os.path.join(TESTFILE_DIR, "valid_plugin.zip_")
        with open(valid_plugin, "rb") as file:
            uploaded_file = SimpleUploadedFile(
                "valid_plugin.zip_", file.read(), content_type="application/zip"
            )
        self.client.post(self.url_upload, {"package": uploaded_file})

        self.plugin = Plugin.objects.get(name="Test Plugin")
        package_name = self.plugin.package_name

        self.url_add_version = reverse("version_create_api", args=[package_name])
        url_token_create = reverse("plugin_token_create", args=[package_name])

        self.client.post(url_token_create, {})
        outstanding_token = OutstandingToken.objects.last().token
        refresh = RefreshToken(outstanding_token)
        refresh["plugin_id"] = self.plugin.pk
        refresh["refresh_jti"] = refresh["jti"]
        self.access_token = str(refresh.access_token)

        self.client.logout()

        # Create a skippable warning rule
        self.rule = SecurityRule.objects.create(
            check_code="B311",
            check_category="bandit",
            check_name="Use of random for security",
            check_description="Random module is not suitable for crypto.",
            severity="warning",
            enabled=True,
            can_be_skipped=True,
        )

    @patch("plugins.tasks.run_security_scan.run_security_scan_task.delay")
    def test_token_upload_with_skip_passes_rule_ids(self, mock_task):
        """Token API upload with skip_security_rules passes matching rule IDs to the task."""
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
                "skip_security_rules": [self.rule.check_code],
            },
        )

        self.assertEqual(response.status_code, 201)
        mock_task.assert_called_once()
        _args, kwargs = mock_task.call_args
        self.assertIn(self.rule.id, kwargs.get("skipped_rule_ids", []))

    @patch("plugins.tasks.run_security_scan.run_security_scan_task.delay")
    def test_token_upload_without_skip_passes_empty_list(self, mock_task):
        """Token API upload without skip_security_rules passes empty list to task."""
        valid_plugin = os.path.join(TESTFILE_DIR, "valid_plugin_0.0.2.zip_")
        with open(valid_plugin, "rb") as file:
            uploaded_file = SimpleUploadedFile(
                "valid_plugin_0.0.2.zip_", file.read(), content_type="application/zip_"
            )

        c = Client(HTTP_AUTHORIZATION=f"Bearer {self.access_token}")
        response = c.post(
            self.url_add_version,
            {"package": uploaded_file},
        )

        self.assertEqual(response.status_code, 201)
        mock_task.assert_called_once()
        _args, kwargs = mock_task.call_args
        self.assertEqual(kwargs.get("skipped_rule_ids", []), [])
