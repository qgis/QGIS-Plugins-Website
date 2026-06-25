import os
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth.models import Permission, User
from django.contrib.contenttypes.models import ContentType
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from plugins.forms import PackageUploadForm
from plugins.models import VALIDATION_STATUS_VALIDATING, Plugin, PluginVersion


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
    @patch(
        "plugins.tasks.run_security_scan.run_security_scan_task.delay", new=do_nothing
    )
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
    def test_new_version_not_auto_approved_for_untrusted_user_on_approved_plugin(self):
        """
        Security: a new version must NOT be auto-approved because the plugin is
        approved. Only user trust (can_approve permission) should grant approval.
        """
        self.client.login(username="testuser", password="testpassword")

        # Upload the initial plugin
        valid_plugin = os.path.join(TESTFILE_DIR, "valid_plugin.zip_")
        with open(valid_plugin, "rb") as file:
            uploaded_file = SimpleUploadedFile(
                "valid_plugin.zip_", file.read(), content_type="application/zip"
            )
        self.client.post(self.url, {"package": uploaded_file})

        plugin = Plugin.objects.get(name="Test Plugin")

        # Simulate staff approval of the existing version
        version = PluginVersion.objects.get(plugin=plugin, version="0.0.1")
        version.approved = True
        version.save()
        self.assertTrue(version.approved)

        # Upload a new version as the same untrusted user
        valid_plugin_v2 = os.path.join(TESTFILE_DIR, "valid_plugin_0.0.2.zip_")
        with open(valid_plugin_v2, "rb") as file:
            uploaded_file_v2 = SimpleUploadedFile(
                "valid_plugin_0.0.2.zip_", file.read(), content_type="application/zip"
            )
        response = self.client.post(self.url, {"package": uploaded_file_v2})

        self.assertEqual(response.status_code, 302)
        new_version = PluginVersion.objects.get(plugin=plugin, version="0.0.2")
        self.assertFalse(
            new_version.approved,
            "New version must NOT be auto-approved just because the plugin is approved; "
            "only user trust (can_approve) should grant approval.",
        )

    @patch("plugins.tasks.generate_plugins_xml", new=do_nothing)
    @patch("plugins.validator._check_url_link", new=do_nothing)
    @patch("plugins.tasks.run_security_scan.run_security_scan_task.delay")
    def test_new_version_queued_for_scan_for_trusted_user(self, mock_scan_delay):
        """
        A trusted user's upload starts async security validation, NOT immediate
        approval. The version is created with approved=False and
        validation_status=VALIDATING, and the security scan task is queued.
        Approval happens asynchronously after the scan passes.
        """
        ct = ContentType.objects.get_for_model(Plugin)
        perm = Permission.objects.get(codename="can_approve", content_type=ct)
        self.user.user_permissions.add(perm)
        # Refresh to bust Django's permission cache
        self.user = self.user.__class__.objects.get(pk=self.user.pk)

        self.client.login(username="testuser", password="testpassword")

        # Upload the initial plugin
        valid_plugin = os.path.join(TESTFILE_DIR, "valid_plugin.zip_")
        with open(valid_plugin, "rb") as file:
            uploaded_file = SimpleUploadedFile(
                "valid_plugin.zip_", file.read(), content_type="application/zip"
            )
        self.client.post(self.url, {"package": uploaded_file})

        plugin = Plugin.objects.get(name="Test Plugin")

        # Upload a second version as the trusted user
        valid_plugin_v2 = os.path.join(TESTFILE_DIR, "valid_plugin_0.0.2.zip_")
        with open(valid_plugin_v2, "rb") as file:
            uploaded_file_v2 = SimpleUploadedFile(
                "valid_plugin_0.0.2.zip_", file.read(), content_type="application/zip"
            )
        response = self.client.post(self.url, {"package": uploaded_file_v2})

        self.assertEqual(response.status_code, 302)
        new_version = PluginVersion.objects.get(plugin=plugin, version="0.0.2")
        self.assertFalse(
            new_version.approved,
            "Upload always starts unapproved; approval is deferred to the async security scan.",
        )
        self.assertEqual(
            new_version.validation_status,
            VALIDATION_STATUS_VALIDATING,
            "New version should be in VALIDATING state immediately after upload.",
        )
        mock_scan_delay.assert_any_call(
            new_version.pk, auto_approve=False, skipped_rule_ids=[]
        )

    @patch("plugins.tasks.generate_plugins_xml", new=do_nothing)
    @patch("plugins.validator._check_url_link", new=do_nothing)
    @patch("plugins.tasks.run_security_scan.run_security_scan_task.delay")
    def test_new_version_publish_immediately_opt_in_for_trusted_user(
        self, mock_scan_delay
    ):
        """
        A trusted user who checks "Publish immediately" on the upload form should
        have the scan task called with auto_approve=True.
        """
        ct = ContentType.objects.get_for_model(Plugin)
        perm = Permission.objects.get(codename="can_approve", content_type=ct)
        self.user.user_permissions.add(perm)
        self.user = self.user.__class__.objects.get(pk=self.user.pk)

        self.client.login(username="testuser", password="testpassword")

        valid_plugin = os.path.join(TESTFILE_DIR, "valid_plugin.zip_")
        with open(valid_plugin, "rb") as file:
            uploaded_file = SimpleUploadedFile(
                "valid_plugin.zip_", file.read(), content_type="application/zip"
            )
        # POST with opt-in checkbox ticked
        response = self.client.post(
            self.url, {"package": uploaded_file, "auto_approve_after_scan": "on"}
        )

        self.assertEqual(response.status_code, 302)
        version = PluginVersion.objects.get(plugin__name="Test Plugin", version="0.0.1")
        # Still starts unapproved — approval happens in the task
        self.assertFalse(version.approved)
        self.assertEqual(version.validation_status, VALIDATION_STATUS_VALIDATING)
        # Task must be queued with auto_approve=True
        mock_scan_delay.assert_any_call(
            version.pk, auto_approve=True, skipped_rule_ids=[]
        )

    def tearDown(self):
        self.client.logout()
