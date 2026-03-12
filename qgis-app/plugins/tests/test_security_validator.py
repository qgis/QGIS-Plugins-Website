"""
Unit tests for the blocking security validator feature (QEP-408 / Issue #216).

Tests cover:
 - PluginVersion.validation_status field and is_available property
 - Async Celery task: run_security_scan_task
 - Upload flow: validation_status set to validating, task queued
 - Download blocking for validating/blocked versions
 - Approval blocking for validating/blocked versions
 - Manual re-scan view (version_rescan)
 - Stage 1 (upload confirmation) and Stage 2 (results) email notifications
"""

import os
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import Permission, User
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, RequestFactory, TestCase, override_settings
from django.urls import reverse

from plugins.models import (
    Plugin,
    PluginVersion,
    PluginVersionSecurityScan,
    VALIDATION_STATUS_BLOCKED,
    VALIDATION_STATUS_PENDING,
    VALIDATION_STATUS_VALIDATED,
    VALIDATION_STATUS_VALIDATING,
)
from plugins.tasks.run_security_scan import (
    _maybe_auto_approve,
    _send_validation_results_email,
    run_security_scan_task,
)

TESTFILE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "testfiles"))


def _make_plugin_version(user, validation_status=VALIDATION_STATUS_PENDING, approved=False):
    """Create a minimal Plugin + PluginVersion for testing."""
    plugin = Plugin.objects.create(
        package_name="test-security-pkg",
        created_by=user,
        name="Test Security Plugin",
    )
    version = PluginVersion.objects.create(
        plugin=plugin,
        version="1.0.0",
        downloads=0,
        created_by=user,
        approved=approved,
        validation_status=validation_status,
        package=SimpleUploadedFile("test.zip", b"PK\x05\x06" + b"\x00" * 18),
        min_qg_version="3.0.0",
        max_qg_version="3.99.0",
    )
    return plugin, version


# ---------------------------------------------------------------------------
# Model / property tests
# ---------------------------------------------------------------------------

class ValidationStatusPropertyTest(TestCase):
    """Tests for PluginVersion.is_available and validation_status field."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="propuser", password="pass", email="prop@test.com"
        )

    def test_is_available_pending(self):
        _, version = _make_plugin_version(self.user, VALIDATION_STATUS_PENDING)
        self.assertTrue(version.is_available)

    def test_is_available_validating(self):
        _, version = _make_plugin_version(self.user, VALIDATION_STATUS_VALIDATING)
        self.assertFalse(version.is_available)

    def test_is_available_validated(self):
        _, version = _make_plugin_version(self.user, VALIDATION_STATUS_VALIDATED)
        self.assertTrue(version.is_available)

    def test_is_available_blocked(self):
        _, version = _make_plugin_version(self.user, VALIDATION_STATUS_BLOCKED)
        self.assertFalse(version.is_available)

    def test_default_validation_status_is_pending(self):
        plugin = Plugin.objects.create(
            package_name="default-status-pkg",
            created_by=self.user,
        )
        version = PluginVersion.objects.create(
            plugin=plugin,
            version="0.1.0",
            downloads=0,
            created_by=self.user,
            package=SimpleUploadedFile("t.zip", b"PK\x05\x06" + b"\x00" * 18),
            min_qg_version="3.0.0",
            max_qg_version="3.99.0",
        )
        self.assertEqual(version.validation_status, VALIDATION_STATUS_PENDING)


# ---------------------------------------------------------------------------
# Async task tests
# ---------------------------------------------------------------------------

class RunSecurityScanTaskTest(TestCase):
    """Tests for the run_security_scan_task Celery task."""

    fixtures = ["fixtures/auth.json"]

    def setUp(self):
        self.user = User.objects.create_user(
            username="taskuser", password="pass", email="task@test.com"
        )
        self.plugin, self.version = _make_plugin_version(
            self.user, VALIDATION_STATUS_VALIDATING
        )

    def _make_security_scan(self, critical_count=0, passed_checks=5, total_checks=5):
        """Create a PluginVersionSecurityScan with the given critical_count."""
        scan = PluginVersionSecurityScan.objects.create(
            plugin_version=self.version,
            scan_report={
                "checks": [],
                "summary": {
                    "total_checks": total_checks,
                    "passed": passed_checks,
                    "failed": total_checks - passed_checks,
                    "critical": critical_count,
                    "warning": 0,
                    "info": 0,
                    "files_scanned": 1,
                },
            },
            critical_count=critical_count,
            warning_count=0,
            passed_checks=passed_checks,
            total_checks=total_checks,
            files_scanned=1,
        )
        return scan

    @override_settings(DEBUG=True)
    @patch("plugins.security_utils.run_security_scan")
    def test_task_sets_validated_when_no_critical_issues(self, mock_scan):
        """Task sets validation_status='validated' when critical_count == 0."""
        scan = self._make_security_scan(critical_count=0)
        mock_scan.return_value = scan

        run_security_scan_task(self.version.pk)

        self.version.refresh_from_db()
        self.assertEqual(self.version.validation_status, VALIDATION_STATUS_VALIDATED)

    @override_settings(DEBUG=True)
    @patch("plugins.security_utils.run_security_scan")
    def test_task_sets_blocked_when_critical_issues(self, mock_scan):
        """Task sets validation_status='blocked' when critical_count > 0."""
        scan = self._make_security_scan(critical_count=2)
        mock_scan.return_value = scan

        run_security_scan_task(self.version.pk)

        self.version.refresh_from_db()
        self.assertEqual(self.version.validation_status, VALIDATION_STATUS_BLOCKED)

    @override_settings(DEBUG=True)
    @patch("plugins.security_utils.run_security_scan")
    def test_task_blocked_version_not_approved(self, mock_scan):
        """Blocked versions must not be auto-approved."""
        scan = self._make_security_scan(critical_count=1)
        mock_scan.return_value = scan

        run_security_scan_task(self.version.pk)

        self.version.refresh_from_db()
        self.assertFalse(self.version.approved)

    @override_settings(DEBUG=True)
    @patch("plugins.security_utils.run_security_scan")
    def test_manual_scan_does_not_change_status(self, mock_scan):
        """Manual re-scans must NOT change validation_status."""
        self.version.validation_status = VALIDATION_STATUS_VALIDATED
        self.version.save()

        # Scan reports critical issues, but because is_manual=True status must not change
        scan = self._make_security_scan(critical_count=3)
        mock_scan.return_value = scan

        run_security_scan_task(self.version.pk, is_manual=True)

        self.version.refresh_from_db()
        # Must remain validated, not blocked
        self.assertEqual(self.version.validation_status, VALIDATION_STATUS_VALIDATED)

    @override_settings(DEBUG=True)
    @patch("plugins.security_utils.run_security_scan")
    def test_task_handles_nonexistent_version(self, mock_scan):
        """Task must not raise when the PluginVersion no longer exists."""
        # Should complete without error
        run_security_scan_task(99999)
        mock_scan.assert_not_called()

    @override_settings(DEBUG=True)
    @patch("plugins.security_utils.run_security_scan")
    def test_task_scan_tool_failure_treated_as_validated(self, mock_scan):
        """When the scan tool fails (returns None), version is still validated."""
        mock_scan.return_value = None

        run_security_scan_task(self.version.pk)

        self.version.refresh_from_db()
        self.assertEqual(self.version.validation_status, VALIDATION_STATUS_VALIDATED)


# ---------------------------------------------------------------------------
# Auto-approve helper tests
# ---------------------------------------------------------------------------

class MaybeAutoApproveTest(TestCase):
    """Tests for the _maybe_auto_approve helper."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="approveuser", password="pass", email="approve@test.com"
        )
        self.plugin, self.version = _make_plugin_version(self.user)

    def test_auto_approve_for_trusted_user(self):
        """Users with 'can_approve' permission are auto-approved."""
        permission = Permission.objects.get(codename="can_approve")
        self.user.user_permissions.add(permission)
        # Refresh from DB to pick up new permissions
        self.user = User.objects.get(pk=self.user.pk)
        self.version.created_by = self.user

        _maybe_auto_approve(self.version)

        self.assertTrue(self.version.approved)

    def test_auto_approve_when_plugin_already_approved(self):
        """Versions of already-approved plugins are auto-approved."""
        # Approve the plugin by approving an older version
        self.plugin.latest_approved_version = self.version
        old_version = PluginVersion.objects.create(
            plugin=self.plugin,
            version="0.9.0",
            downloads=0,
            created_by=self.user,
            approved=True,
            package=SimpleUploadedFile("t2.zip", b"PK\x05\x06" + b"\x00" * 18),
            min_qg_version="3.0.0",
            max_qg_version="3.99.0",
        )
        # Plugin.approved returns True when any version is approved
        self.assertTrue(self.plugin.approved)

        _maybe_auto_approve(self.version)

        self.assertTrue(self.version.approved)

    def test_no_auto_approve_for_untrusted_user(self):
        """Regular users without 'can_approve' are NOT auto-approved."""
        _maybe_auto_approve(self.version)
        self.assertFalse(self.version.approved)


# ---------------------------------------------------------------------------
# Upload flow tests
# ---------------------------------------------------------------------------

class PluginUploadValidationFlowTest(TestCase):
    """Tests that the upload view sets validating status and queues the task."""

    fixtures = ["fixtures/auth.json"]

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username="uploaduser", password="testpass", email="upload@test.com"
        )
        self.url = reverse("plugin_upload")

    @override_settings(MEDIA_ROOT="api/tests", DEBUG=True)
    @patch("plugins.tasks.generate_plugins_xml", new=lambda *a, **kw: None)
    @patch("plugins.validator._check_url_link", new=lambda *a, **kw: None)
    @patch("plugins.tasks.run_security_scan.run_security_scan_task.delay")
    def test_upload_sets_validating_status(self, mock_task):
        """Freshly uploaded version must have validation_status='validating'."""
        self.client.login(username="uploaduser", password="testpass")
        valid_plugin = os.path.join(TESTFILE_DIR, "valid_plugin.zip_")
        with open(valid_plugin, "rb") as f:
            uploaded = SimpleUploadedFile("valid_plugin.zip_", f.read(), content_type="application/zip")

        response = self.client.post(self.url, {"package": uploaded})

        self.assertEqual(response.status_code, 302)
        version = PluginVersion.objects.filter(plugin__name="Test Plugin").first()
        self.assertIsNotNone(version)
        self.assertEqual(version.validation_status, VALIDATION_STATUS_VALIDATING)

    @override_settings(MEDIA_ROOT="api/tests", DEBUG=True)
    @patch("plugins.tasks.generate_plugins_xml", new=lambda *a, **kw: None)
    @patch("plugins.validator._check_url_link", new=lambda *a, **kw: None)
    @patch("plugins.tasks.run_security_scan.run_security_scan_task.delay")
    def test_upload_sets_approved_false(self, mock_task):
        """Freshly uploaded version must be unapproved regardless of user trust."""
        self.client.login(username="uploaduser", password="testpass")
        valid_plugin = os.path.join(TESTFILE_DIR, "valid_plugin.zip_")
        with open(valid_plugin, "rb") as f:
            uploaded = SimpleUploadedFile("valid_plugin.zip_", f.read(), content_type="application/zip")

        self.client.post(self.url, {"package": uploaded})

        version = PluginVersion.objects.filter(plugin__name="Test Plugin").first()
        self.assertIsNotNone(version)
        self.assertFalse(version.approved)

    @override_settings(MEDIA_ROOT="api/tests", DEBUG=True)
    @patch("plugins.tasks.generate_plugins_xml", new=lambda *a, **kw: None)
    @patch("plugins.validator._check_url_link", new=lambda *a, **kw: None)
    @patch("plugins.tasks.run_security_scan.run_security_scan_task.delay")
    def test_upload_queues_security_scan_task(self, mock_task):
        """Security scan task must be queued (delay called) after upload."""
        self.client.login(username="uploaduser", password="testpass")
        valid_plugin = os.path.join(TESTFILE_DIR, "valid_plugin.zip_")
        with open(valid_plugin, "rb") as f:
            uploaded = SimpleUploadedFile("valid_plugin.zip_", f.read(), content_type="application/zip")

        self.client.post(self.url, {"package": uploaded})

        mock_task.assert_called_once()
        # First argument must be the pk of the newly created version
        version = PluginVersion.objects.filter(plugin__name="Test Plugin").first()
        self.assertEqual(mock_task.call_args[0][0], version.pk)


# ---------------------------------------------------------------------------
# Download blocking tests
# ---------------------------------------------------------------------------

class VersionDownloadBlockingTest(TestCase):
    """Tests that download is blocked for validating/blocked versions."""

    def setUp(self):
        self.factory = RequestFactory()
        self.user = User.objects.create_user(
            username="dluser", password="pass", email="dl@test.com"
        )
        self.plugin, self.version = _make_plugin_version(self.user)

    def _get_download(self):
        url = reverse("version_download", args=[self.plugin.package_name, self.version.version])
        c = Client()
        return c.get(url)

    def test_download_allowed_for_pending(self):
        """Pending (legacy) versions are downloadable."""
        self.version.validation_status = VALIDATION_STATUS_PENDING
        self.version.save()
        response = self._get_download()
        # May be 200 or redirect; must not be 403
        self.assertNotEqual(response.status_code, 403)

    def test_download_allowed_when_approved(self):
        """Approved versions are always downloadable, regardless of validation_status."""
        self.version.approved = True
        self.version.validation_status = VALIDATION_STATUS_BLOCKED  # hypothetical edge case
        self.version.save()
        response = self._get_download()
        self.assertNotEqual(response.status_code, 403)

    def test_download_blocked_when_validating(self):
        """Unapproved versions in 'validating' state must return 403."""
        self.version.approved = False
        self.version.validation_status = VALIDATION_STATUS_VALIDATING
        self.version.save()
        response = self._get_download()
        self.assertEqual(response.status_code, 403)

    def test_download_blocked_when_blocked(self):
        """Unapproved versions in 'blocked' state must return 403."""
        self.version.approved = False
        self.version.validation_status = VALIDATION_STATUS_BLOCKED
        self.version.save()
        response = self._get_download()
        self.assertEqual(response.status_code, 403)

    def test_download_allowed_when_validated(self):
        """Unapproved but validated versions can be downloaded."""
        self.version.approved = False
        self.version.validation_status = VALIDATION_STATUS_VALIDATED
        self.version.save()
        response = self._get_download()
        self.assertNotEqual(response.status_code, 403)


# ---------------------------------------------------------------------------
# Approval blocking tests
# ---------------------------------------------------------------------------

class VersionApproveBlockingTest(TestCase):
    """Tests that approval is blocked for validating/blocked versions."""

    fixtures = ["fixtures/auth.json"]

    def setUp(self):
        self.client = Client()
        self.staff_user = User.objects.create_user(
            username="staffapprover", password="pass", email="staff@test.com",
            is_staff=True,
        )
        self.staff_user.user_permissions.add(
            Permission.objects.get(codename="can_approve")
        )
        self.plugin_owner = User.objects.create_user(
            username="plgowner2", password="pass", email="owner2@test.com"
        )
        self.plugin, self.version = _make_plugin_version(
            self.plugin_owner, VALIDATION_STATUS_VALIDATED
        )
        # staff_user.is_staff=True is sufficient for check_plugin_version_approval_rights

    def _post_approve(self):
        self.client.login(username="staffapprover", password="pass")
        url = reverse("version_approve", args=[self.plugin.package_name, self.version.version])
        return self.client.post(url)

    def test_approve_allowed_when_validated(self):
        """Staff can approve a validated version."""
        self.version.validation_status = VALIDATION_STATUS_VALIDATED
        self.version.save()
        response = self._post_approve()
        # Should redirect (302) after success
        self.assertEqual(response.status_code, 302)
        self.version.refresh_from_db()
        self.assertTrue(self.version.approved)

    def test_approve_blocked_when_validating(self):
        """Staff cannot approve a version still being validated."""
        self.version.validation_status = VALIDATION_STATUS_VALIDATING
        self.version.save()
        response = self._post_approve()
        # Should redirect back with an error message
        self.assertEqual(response.status_code, 302)
        self.version.refresh_from_db()
        self.assertFalse(self.version.approved)

    def test_approve_blocked_when_blocked_status(self):
        """Staff cannot approve a version blocked by security checks."""
        self.version.validation_status = VALIDATION_STATUS_BLOCKED
        self.version.save()
        response = self._post_approve()
        self.assertEqual(response.status_code, 302)
        self.version.refresh_from_db()
        self.assertFalse(self.version.approved)


# ---------------------------------------------------------------------------
# Manual re-scan view tests
# ---------------------------------------------------------------------------

class VersionRescanViewTest(TestCase):
    """Tests for the version_rescan view."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username="rescanuser", password="pass", email="rescan@test.com"
        )
        self.plugin, self.version = _make_plugin_version(
            self.user, VALIDATION_STATUS_VALIDATED
        )

    @patch("plugins.views.run_security_scan_task")
    def test_rescan_requires_login(self, mock_task):
        """Anonymous users must be redirected to the login page."""
        url = reverse("version_rescan", args=[self.plugin.package_name, self.version.version])
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response["Location"])
        mock_task.delay.assert_not_called()

    @patch("plugins.views.run_security_scan_task")
    def test_rescan_requires_post(self, mock_task):
        """GET requests to rescan must not trigger the task."""
        self.client.login(username="rescanuser", password="pass")
        url = reverse("version_rescan", args=[self.plugin.package_name, self.version.version])
        response = self.client.get(url)
        # Should return 405 (method not allowed)
        self.assertEqual(response.status_code, 405)
        mock_task.delay.assert_not_called()

    @patch("plugins.views.run_security_scan_task")
    def test_rescan_owner_can_trigger(self, mock_task):
        """The plugin owner can trigger a manual re-scan."""
        self.client.login(username="rescanuser", password="pass")
        url = reverse("version_rescan", args=[self.plugin.package_name, self.version.version])
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)
        mock_task.delay.assert_called_once_with(self.version.pk, is_manual=True)

    @patch("plugins.views.run_security_scan_task")
    def test_rescan_non_owner_denied(self, mock_task):
        """A user that doesn't own the plugin cannot trigger a re-scan."""
        other_user = User.objects.create_user(
            username="otheruser2", password="pass", email="other2@test.com"
        )
        self.client.login(username="otheruser2", password="pass")
        url = reverse("version_rescan", args=[self.plugin.package_name, self.version.version])
        response = self.client.post(url)
        # Should redirect with an error, not call task
        self.assertEqual(response.status_code, 302)
        mock_task.delay.assert_not_called()


# ---------------------------------------------------------------------------
# Email notification tests
# ---------------------------------------------------------------------------

class UploadConfirmationEmailTest(TestCase):
    """Tests for Stage 1 upload confirmation email."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="emailuser", password="pass", email="emailuser@test.com"
        )
        self.plugin, self.version = _make_plugin_version(self.user, VALIDATION_STATUS_VALIDATING)

    @override_settings(DEBUG=False)
    def test_upload_confirmation_email_sent(self):
        """Stage 1 email is sent to plugin editors on upload."""
        from plugins.views import send_upload_confirmation_email

        mail.outbox = []
        send_upload_confirmation_email(self.version)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("emailuser@test.com", mail.outbox[0].to)
        self.assertIn(self.plugin.name, mail.outbox[0].subject)
        self.assertIn(self.version.version, mail.outbox[0].subject)

    @override_settings(DEBUG=True)
    def test_upload_confirmation_email_not_sent_in_debug(self):
        """Stage 1 email must NOT be sent when DEBUG=True."""
        from plugins.views import send_upload_confirmation_email

        mail.outbox = []
        send_upload_confirmation_email(self.version)
        self.assertEqual(len(mail.outbox), 0)

    @override_settings(DEBUG=False)
    def test_upload_confirmation_email_body_contains_validating_status(self):
        """Stage 1 email body must mention that validation is in progress."""
        from plugins.views import send_upload_confirmation_email

        mail.outbox = []
        send_upload_confirmation_email(self.version)
        body = mail.outbox[0].body.lower()
        # Should mention validation / security check
        self.assertTrue(
            "validat" in body or "security" in body,
            "Email body should mention validation or security checks",
        )


class ValidationResultsEmailTest(TestCase):
    """Tests for Stage 2 validation results email."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="resultsuser", password="pass", email="results@test.com"
        )
        self.plugin, self.version = _make_plugin_version(self.user, VALIDATION_STATUS_VALIDATED)

    def _make_scan(self, critical_count=0):
        return PluginVersionSecurityScan.objects.create(
            plugin_version=self.version,
            scan_report={
                "checks": [],
                "summary": {
                    "total_checks": 5,
                    "passed": 5 - critical_count,
                    "failed": critical_count,
                    "critical": critical_count,
                    "warning": 0,
                    "info": 0,
                    "files_scanned": 1,
                },
            },
            critical_count=critical_count,
            warning_count=0,
            passed_checks=5 - critical_count,
            total_checks=5,
            files_scanned=1,
        )

    @override_settings(DEBUG=False)
    def test_validated_results_email_sent(self):
        """Stage 2 email is sent when plugin is validated (no critical issues)."""
        scan = self._make_scan(critical_count=0)
        self.version.validation_status = VALIDATION_STATUS_VALIDATED

        mail.outbox = []
        _send_validation_results_email(self.version, scan)

        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("results@test.com", mail.outbox[0].to)

    @override_settings(DEBUG=False)
    def test_blocked_results_email_sent(self):
        """Stage 2 email is sent when plugin is blocked (critical issues found)."""
        scan = self._make_scan(critical_count=2)
        self.version.validation_status = VALIDATION_STATUS_BLOCKED

        mail.outbox = []
        _send_validation_results_email(self.version, scan)

        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("results@test.com", mail.outbox[0].to)

    @override_settings(DEBUG=False)
    def test_blocked_email_subject_indicates_failure(self):
        """Stage 2 email subject must indicate failure for blocked versions."""
        scan = self._make_scan(critical_count=1)
        self.version.validation_status = VALIDATION_STATUS_BLOCKED

        mail.outbox = []
        _send_validation_results_email(self.version, scan)

        subject = mail.outbox[0].subject.lower()
        self.assertTrue(
            "block" in subject or "fail" in subject or "critical" in subject or "issue" in subject,
            f"Unexpected subject for blocked email: {mail.outbox[0].subject}",
        )

    @override_settings(DEBUG=True)
    def test_results_email_not_sent_in_debug(self):
        """Stage 2 email must NOT be sent when DEBUG=True."""
        scan = self._make_scan(critical_count=0)

        mail.outbox = []
        _send_validation_results_email(self.version, scan)

        self.assertEqual(len(mail.outbox), 0)
