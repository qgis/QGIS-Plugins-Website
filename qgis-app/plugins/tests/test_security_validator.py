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
 - Security rule skipping: form choices, task integration, audit trail
 - Config file bypass: .bandit / .secrets.baseline / .flake8 handling
"""

import io
import os
import zipfile as zipfile_module
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import Permission, User
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, RequestFactory, TestCase, override_settings
from django.urls import reverse
from plugins.forms import PackageUploadForm
from plugins.models import (
    VALIDATION_STATUS_BLOCKED,
    VALIDATION_STATUS_PENDING,
    VALIDATION_STATUS_VALIDATED,
    VALIDATION_STATUS_VALIDATED_WITH_CONFIG,
    VALIDATION_STATUS_VALIDATING,
    Plugin,
    PluginVersion,
    PluginVersionSecurityRuleSkip,
    PluginVersionSecurityScan,
    SecurityRule,
)
from plugins.security_scanner import SECURITY_CONFIG_FILES, PluginSecurityScanner
from plugins.security_utils import run_security_scan
from plugins.tasks.run_security_scan import (
    _send_validation_results_email,
    run_security_scan_task,
)
from plugins.views import send_upload_confirmation_email

TESTFILE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "testfiles"))


def _make_plugin_version(
    user, validation_status=VALIDATION_STATUS_PENDING, approved=False
):
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
        self.assertFalse(version.is_available)

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
    @patch("plugins.tasks.run_security_scan.run_security_scan")
    def test_task_sets_validated_when_no_critical_issues(self, mock_scan):
        """Task sets validation_status='validated' when critical_count == 0."""
        scan = self._make_security_scan(critical_count=0)
        mock_scan.return_value = scan

        run_security_scan_task(self.version.pk)

        self.version.refresh_from_db()
        self.assertEqual(self.version.validation_status, VALIDATION_STATUS_VALIDATED)

    @override_settings(DEBUG=True)
    @patch("plugins.tasks.run_security_scan.run_security_scan")
    def test_task_sets_blocked_when_critical_issues(self, mock_scan):
        """Task sets validation_status='blocked' when critical_count > 0."""
        scan = self._make_security_scan(critical_count=2)
        mock_scan.return_value = scan

        run_security_scan_task(self.version.pk)

        self.version.refresh_from_db()
        self.assertEqual(self.version.validation_status, VALIDATION_STATUS_BLOCKED)

    @override_settings(DEBUG=True)
    @patch("plugins.tasks.run_security_scan.run_security_scan")
    def test_task_blocked_version_not_approved(self, mock_scan):
        """Blocked versions must not be auto-approved."""
        scan = self._make_security_scan(critical_count=1)
        mock_scan.return_value = scan

        run_security_scan_task(self.version.pk)

        self.version.refresh_from_db()
        self.assertFalse(self.version.approved)

    @override_settings(DEBUG=True)
    @patch("plugins.tasks.run_security_scan.run_security_scan")
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
    @patch("plugins.tasks.run_security_scan.run_security_scan")
    def test_task_handles_nonexistent_version(self, mock_scan):
        """Task must not raise when the PluginVersion no longer exists."""
        # Should complete without error
        run_security_scan_task(99999)
        mock_scan.assert_not_called()

    @override_settings(DEBUG=True)
    @patch("plugins.tasks.run_security_scan.run_security_scan")
    def test_task_scan_tool_failure_treated_as_validated(self, mock_scan):
        """When the scan tool fails (returns None), version is still validated."""
        mock_scan.return_value = None

        run_security_scan_task(self.version.pk)

        self.version.refresh_from_db()
        self.assertEqual(self.version.validation_status, VALIDATION_STATUS_VALIDATED)


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
            uploaded = SimpleUploadedFile(
                "valid_plugin.zip_", f.read(), content_type="application/zip"
            )

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
            uploaded = SimpleUploadedFile(
                "valid_plugin.zip_", f.read(), content_type="application/zip"
            )

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
            uploaded = SimpleUploadedFile(
                "valid_plugin.zip_", f.read(), content_type="application/zip"
            )

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
        url = reverse(
            "version_download", args=[self.plugin.package_name, self.version.version]
        )
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
        self.version.validation_status = (
            VALIDATION_STATUS_BLOCKED  # hypothetical edge case
        )
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
            username="staffapprover",
            password="pass",
            email="staff@test.com",
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
        url = reverse(
            "version_approve", args=[self.plugin.package_name, self.version.version]
        )
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
        url = reverse(
            "version_rescan", args=[self.plugin.package_name, self.version.version]
        )
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response["Location"])
        mock_task.delay.assert_not_called()

    @patch("plugins.views.run_security_scan_task")
    def test_rescan_requires_post(self, mock_task):
        """GET requests to rescan must not trigger the task."""
        self.client.login(username="rescanuser", password="pass")
        url = reverse(
            "version_rescan", args=[self.plugin.package_name, self.version.version]
        )
        response = self.client.get(url)
        # Should return 405 (method not allowed)
        self.assertEqual(response.status_code, 405)
        mock_task.delay.assert_not_called()

    @patch("plugins.views.run_security_scan_task")
    def test_rescan_owner_can_trigger(self, mock_task):
        """The plugin owner can trigger a manual re-scan."""
        self.client.login(username="rescanuser", password="pass")
        url = reverse(
            "version_rescan", args=[self.plugin.package_name, self.version.version]
        )
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
        url = reverse(
            "version_rescan", args=[self.plugin.package_name, self.version.version]
        )
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
        self.plugin, self.version = _make_plugin_version(
            self.user, VALIDATION_STATUS_VALIDATING
        )

    @override_settings(DEBUG=False)
    def test_upload_confirmation_email_sent(self):
        """Stage 1 email is sent to plugin editors on upload."""
        mail.outbox = []
        send_upload_confirmation_email(self.version)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("emailuser@test.com", mail.outbox[0].to)
        self.assertIn(self.plugin.name, mail.outbox[0].subject)
        self.assertIn(self.version.version, mail.outbox[0].subject)

    @override_settings(DEBUG=True)
    def test_upload_confirmation_email_not_sent_in_debug(self):
        """Stage 1 email must NOT be sent when DEBUG=True."""
        mail.outbox = []
        send_upload_confirmation_email(self.version)
        self.assertEqual(len(mail.outbox), 0)

    @override_settings(DEBUG=False)
    def test_upload_confirmation_email_body_contains_validating_status(self):
        """Stage 1 email body must mention that validation is in progress."""
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
        self.plugin, self.version = _make_plugin_version(
            self.user, VALIDATION_STATUS_VALIDATED
        )

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
            "block" in subject
            or "fail" in subject
            or "critical" in subject
            or "issue" in subject,
            f"Unexpected subject for blocked email: {mail.outbox[0].subject}",
        )

    @override_settings(DEBUG=True)
    def test_results_email_not_sent_in_debug(self):
        """Stage 2 email must NOT be sent when DEBUG=True."""
        scan = self._make_scan(critical_count=0)

        mail.outbox = []
        _send_validation_results_email(self.version, scan)

        self.assertEqual(len(mail.outbox), 0)


# ---------------------------------------------------------------------------
# Security rule skipping tests
# ---------------------------------------------------------------------------


def _make_security_rule(
    check_code,
    check_category="bandit",
    severity="warning",
    enabled=True,
    can_be_skipped=True,
):
    """Create a SecurityRule for use in tests."""
    return SecurityRule.objects.create(
        check_code=check_code,
        check_category=check_category,
        check_name=f"Test rule {check_code}",
        check_description=f"Description for {check_code}",
        severity=severity,
        enabled=enabled,
        can_be_skipped=can_be_skipped,
    )


class SecurityRuleSkipFormTest(TestCase):
    """Tests for the skip_security_rules form field on PackageUploadForm."""

    def setUp(self):
        # Create a mix of rules to verify form choices are filtered correctly
        self.rule_warning_skippable = _make_security_rule(
            "B311", severity="warning", enabled=True, can_be_skipped=True
        )
        self.rule_critical_mandatory = _make_security_rule(
            "B102", severity="critical", enabled=True, can_be_skipped=False
        )
        self.rule_disabled = _make_security_rule(
            "B601", severity="info", enabled=False, can_be_skipped=True
        )

    def _form_choices(self):
        """Return the choice IDs offered by the form field."""
        form = PackageUploadForm()
        return [
            choice_id for choice_id, _ in form.fields["skip_security_rules"].choices
        ]

    def test_form_includes_enabled_skippable_rules(self):
        """Form must include enabled+skippable rules as choices."""
        choices = self._form_choices()
        self.assertIn(self.rule_warning_skippable.check_code, choices)

    def test_form_excludes_non_skippable_rules(self):
        """Form must NOT include critical (non-skippable) rules."""
        choices = self._form_choices()
        self.assertNotIn(self.rule_critical_mandatory.check_code, choices)

    def test_form_excludes_disabled_rules(self):
        """Form must NOT include disabled rules, even if skippable."""
        choices = self._form_choices()
        self.assertNotIn(self.rule_disabled.check_code, choices)

    def test_choice_label_format(self):
        """Choice labels must be in format 'CODE: name (severity)'."""
        form = PackageUploadForm()
        choice_dict = dict(form.fields["skip_security_rules"].choices)
        label = choice_dict.get(self.rule_warning_skippable.check_code, "")
        self.assertIn("B311", label)
        self.assertIn("warning", label.lower())

    def test_non_skippable_rule_id_not_valid_choice(self):
        """Submitting a non-skippable rule code must fail form validation."""
        form = PackageUploadForm(
            data={"skip_security_rules": [self.rule_critical_mandatory.check_code]}
        )
        # The field uses MultipleChoiceField which validates against choices
        form.is_valid()
        self.assertIn("skip_security_rules", form.errors)


class SecurityRuleSkipUploadTest(TestCase):
    """Tests that the upload view passes skipped_rule_ids to the task correctly."""

    fixtures = ["fixtures/auth.json"]

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username="skipruleuser", password="testpass", email="skip@test.com"
        )
        self.url = reverse("plugin_upload")
        # Create a skippable rule
        self.rule = _make_security_rule(
            "B311", severity="warning", enabled=True, can_be_skipped=True
        )

    @override_settings(MEDIA_ROOT="api/tests", DEBUG=True)
    @patch("plugins.tasks.generate_plugins_xml", new=lambda *a, **kw: None)
    @patch("plugins.validator._check_url_link", new=lambda *a, **kw: None)
    @patch("plugins.tasks.run_security_scan.run_security_scan_task.delay")
    def test_upload_without_skip_passes_empty_list(self, mock_task):
        """Uploading without skip_security_rules passes an empty list to the task."""
        self.client.login(username="skipruleuser", password="testpass")
        valid_plugin = os.path.join(TESTFILE_DIR, "valid_plugin.zip_")
        with open(valid_plugin, "rb") as f:
            uploaded = SimpleUploadedFile(
                "valid_plugin.zip_", f.read(), content_type="application/zip"
            )

        self.client.post(self.url, {"package": uploaded})

        mock_task.assert_called_once()
        _args, kwargs = mock_task.call_args
        self.assertEqual(kwargs.get("skipped_rule_ids", []), [])

    @override_settings(MEDIA_ROOT="api/tests", DEBUG=True)
    @patch("plugins.tasks.generate_plugins_xml", new=lambda *a, **kw: None)
    @patch("plugins.validator._check_url_link", new=lambda *a, **kw: None)
    @patch("plugins.tasks.run_security_scan.run_security_scan_task.delay")
    def test_upload_with_skip_passes_rule_ids_to_task(self, mock_task):
        """Uploading with skip_security_rules passes matching rule IDs to the task."""
        self.client.login(username="skipruleuser", password="testpass")
        valid_plugin = os.path.join(TESTFILE_DIR, "valid_plugin.zip_")
        with open(valid_plugin, "rb") as f:
            uploaded = SimpleUploadedFile(
                "valid_plugin.zip_", f.read(), content_type="application/zip"
            )

        self.client.post(
            self.url,
            {
                "package": uploaded,
                "skip_security_rules": [self.rule.check_code],
            },
        )

        mock_task.assert_called_once()
        _args, kwargs = mock_task.call_args
        self.assertIn(self.rule.id, kwargs.get("skipped_rule_ids", []))


class SecurityRuleSkipTaskTest(TestCase):
    """Tests for skip-rule behavior inside run_security_scan_task."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="skiptaskuser", password="pass", email="skiptask@test.com"
        )
        self.plugin, self.version = _make_plugin_version(
            self.user, VALIDATION_STATUS_VALIDATING
        )
        # Create a warning-only rule that is skippable
        self.warning_rule = _make_security_rule(
            "B311", severity="warning", enabled=True, can_be_skipped=True
        )
        # Create a critical non-skippable rule
        self.critical_rule = _make_security_rule(
            "B102", severity="critical", enabled=True, can_be_skipped=False
        )

    def _make_security_scan(self, critical_count=0, warning_count=0):
        """Helper: create a PluginVersionSecurityScan."""
        total = 5
        passed = total - critical_count - warning_count
        scan = PluginVersionSecurityScan.objects.create(
            plugin_version=self.version,
            scan_report={
                "checks": [],
                "summary": {
                    "total_checks": total,
                    "passed": passed,
                    "failed": critical_count + warning_count,
                    "critical": critical_count,
                    "warnings": warning_count,
                    "info": 0,
                    "files_scanned": 1,
                    "total_issues": critical_count + warning_count,
                },
            },
            critical_count=critical_count,
            warning_count=warning_count,
            passed_checks=passed,
            total_checks=total,
            files_scanned=1,
        )
        return scan

    @override_settings(DEBUG=True)
    @patch("plugins.tasks.run_security_scan.run_security_scan")
    def test_skipped_rule_ids_forwarded_to_scan(self, mock_scan):
        """Task must forward skipped_rule_ids to run_security_scan."""
        scan = self._make_security_scan(critical_count=0)
        mock_scan.return_value = scan

        run_security_scan_task(self.version.pk, skipped_rule_ids=[self.warning_rule.id])

        mock_scan.assert_called_once()
        _args, kwargs = mock_scan.call_args
        self.assertIn(self.warning_rule.id, kwargs.get("skipped_rule_ids", []))

    @override_settings(DEBUG=True)
    @patch("plugins.tasks.run_security_scan.run_security_scan")
    def test_skipping_warning_rule_does_not_block(self, mock_scan):
        """Skipping a warning rule leads to validated status (no critical issues)."""
        # Simulate a scan with no critical issues (warning was skipped)
        scan = self._make_security_scan(critical_count=0, warning_count=0)
        mock_scan.return_value = scan

        run_security_scan_task(self.version.pk, skipped_rule_ids=[self.warning_rule.id])

        self.version.refresh_from_db()
        self.assertEqual(self.version.validation_status, VALIDATION_STATUS_VALIDATED)

    @override_settings(DEBUG=True)
    @patch("plugins.tasks.run_security_scan.run_security_scan")
    def test_critical_issue_still_blocks_even_with_skip_list(self, mock_scan):
        """Critical issues block the version even when a skip list is provided."""
        # critical_rule is not skippable — it still runs and reports critical
        scan = self._make_security_scan(critical_count=1)
        mock_scan.return_value = scan

        run_security_scan_task(self.version.pk, skipped_rule_ids=[self.warning_rule.id])

        self.version.refresh_from_db()
        self.assertEqual(self.version.validation_status, VALIDATION_STATUS_BLOCKED)


class SecurityRuleSkipAuditTest(TestCase):
    """Tests that skipped rules are recorded via PluginVersionSecurityRuleSkip."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="audituser", password="pass", email="audit@test.com"
        )
        self.plugin, self.version = _make_plugin_version(
            self.user, VALIDATION_STATUS_VALIDATING
        )
        self.rule = _make_security_rule(
            "B311", severity="warning", enabled=True, can_be_skipped=True
        )

    def test_skip_record_created_in_run_security_scan(self):
        """run_security_scan must create a PluginVersionSecurityRuleSkip record."""
        with patch("plugins.security_utils.PluginSecurityScanner") as MockScanner:
            mock_report = {
                "summary": {
                    "total_checks": 1,
                    "passed": 1,
                    "failed": 0,
                    "critical": 0,
                    "warnings": 0,
                    "info": 0,
                    "files_scanned": 1,
                    "total_issues": 0,
                },
                "checks": [],
            }
            MockScanner.return_value.scan.return_value = mock_report

            # Use a valid package path (the version's package field is a stub)
            # Patch package.path so it doesn't hit the filesystem
            self.version.package = MagicMock()
            self.version.package.path = "/tmp/fake.zip"

            run_security_scan(self.version, skipped_rule_ids=[self.rule.id])

        skip_records = PluginVersionSecurityRuleSkip.objects.filter(
            plugin_version=self.version, security_rule=self.rule
        )
        self.assertEqual(skip_records.count(), 1)

    def test_non_skippable_rule_not_recorded(self):
        """Non-skippable rules must not have a skip record even if passed in the list."""
        critical_rule = _make_security_rule(
            "B102", severity="critical", enabled=True, can_be_skipped=False
        )

        with patch("plugins.security_utils.PluginSecurityScanner") as MockScanner:
            mock_report = {
                "summary": {
                    "total_checks": 1,
                    "passed": 1,
                    "failed": 0,
                    "critical": 0,
                    "warnings": 0,
                    "info": 0,
                    "files_scanned": 1,
                    "total_issues": 0,
                },
                "checks": [],
            }
            MockScanner.return_value.scan.return_value = mock_report
            self.version.package = MagicMock()
            self.version.package.path = "/tmp/fake.zip"

            run_security_scan(self.version, skipped_rule_ids=[critical_rule.id])

        skip_records = PluginVersionSecurityRuleSkip.objects.filter(
            plugin_version=self.version, security_rule=critical_rule
        )
        self.assertEqual(skip_records.count(), 0)

    def test_disabled_rule_not_recorded(self):
        """Disabled rules must not have a skip record even if passed in the list."""
        disabled_rule = _make_security_rule(
            "B601", severity="info", enabled=False, can_be_skipped=True
        )

        with patch("plugins.security_utils.PluginSecurityScanner") as MockScanner:
            mock_report = {
                "summary": {
                    "total_checks": 1,
                    "passed": 1,
                    "failed": 0,
                    "critical": 0,
                    "warnings": 0,
                    "info": 0,
                    "files_scanned": 1,
                    "total_issues": 0,
                },
                "checks": [],
            }
            MockScanner.return_value.scan.return_value = mock_report
            self.version.package = MagicMock()
            self.version.package.path = "/tmp/fake.zip"

            run_security_scan(self.version, skipped_rule_ids=[disabled_rule.id])

        skip_records = PluginVersionSecurityRuleSkip.objects.filter(
            plugin_version=self.version, security_rule=disabled_rule
        )
        self.assertEqual(skip_records.count(), 0)


# ---------------------------------------------------------------------------
# Config file bypass tests
# ---------------------------------------------------------------------------


def _make_zip_bytes(files: dict) -> bytes:
    """
    Build an in-memory ZIP containing the given files.
    ``files`` is a mapping of {archive_path: content_bytes}.
    """
    buf = io.BytesIO()
    with zipfile_module.ZipFile(buf, "w", zipfile_module.ZIP_DEFLATED) as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return buf.getvalue()


class ConfigFileDetectionTest(TestCase):
    """Tests for SECURITY_CONFIG_FILES constant and _detect_config_files()."""

    def test_security_config_files_constant_contains_expected_files(self):
        """SECURITY_CONFIG_FILES must list all three expected config filenames."""
        for expected in [".bandit", ".secrets.baseline", ".flake8"]:
            self.assertIn(expected, SECURITY_CONFIG_FILES)

    def _scanner_for(self, files: dict) -> PluginSecurityScanner:
        """Return a PluginSecurityScanner pointing at a temp ZIP."""
        import tempfile

        zip_bytes = _make_zip_bytes(files)
        tmp = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
        tmp.write(zip_bytes)
        tmp.flush()
        tmp.close()
        self.addCleanup(os.unlink, tmp.name)
        return PluginSecurityScanner(tmp.name)

    def test_detect_config_files_returns_empty_when_none_present(self):
        """No config files in ZIP -> empty list returned."""
        scanner = self._scanner_for({"myplugin/__init__.py": b"x = 1\n"})
        self.assertEqual(scanner._detect_config_files(), [])

    def test_detect_bandit_config_file(self):
        """.bandit present in ZIP is detected."""
        scanner = self._scanner_for(
            {
                "myplugin/__init__.py": b"x = 1\n",
                "myplugin/.bandit": b"[bandit]\nskips = B311\n",
            }
        )
        self.assertIn(".bandit", scanner._detect_config_files())

    def test_detect_secrets_baseline_file(self):
        """.secrets.baseline present in ZIP is detected."""
        scanner = self._scanner_for(
            {
                "myplugin/__init__.py": b"x = 1\n",
                "myplugin/.secrets.baseline": b"{}",
            }
        )
        self.assertIn(".secrets.baseline", scanner._detect_config_files())

    def test_detect_flake8_config_file(self):
        """.flake8 present in ZIP is detected."""
        scanner = self._scanner_for(
            {
                "myplugin/__init__.py": b"x = 1\n",
                "myplugin/.flake8": b"[flake8]\nextend-ignore = E501\n",
            }
        )
        self.assertIn(".flake8", scanner._detect_config_files())

    def test_detect_multiple_config_files(self):
        """All three config files are detected simultaneously."""
        scanner = self._scanner_for(
            {
                "myplugin/__init__.py": b"x = 1\n",
                "myplugin/.bandit": b"[bandit]\nskips = B311\n",
                "myplugin/.secrets.baseline": b"{}",
                "myplugin/.flake8": b"[flake8]\nextend-ignore = E501\n",
            }
        )
        detected = scanner._detect_config_files()
        for f in [".bandit", ".secrets.baseline", ".flake8"]:
            self.assertIn(f, detected)

    def test_report_includes_config_files_key(self):
        """scan() report must include a 'config_files' key."""
        import tempfile

        zip_bytes = _make_zip_bytes(
            {
                "myplugin/__init__.py": b"x = 1\n",
                "myplugin/.bandit": b"[bandit]\nskips = B311\n",
            }
        )
        tmp = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
        tmp.write(zip_bytes)
        tmp.flush()
        tmp.close()
        self.addCleanup(os.unlink, tmp.name)
        scanner = PluginSecurityScanner(tmp.name)
        report = scanner.scan()
        self.assertIn("config_files", report)
        self.assertIn(".bandit", report["config_files"])


class ConfigFileNotHiddenTest(TestCase):
    """Config files must NOT be flagged as hidden files by the scanner."""

    def _run_suspicious_check(self, files: dict) -> dict:
        """Run the scanner on a ZIP and return the Suspicious Files check result."""
        import tempfile

        zip_bytes = _make_zip_bytes(files)
        tmp = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
        tmp.write(zip_bytes)
        tmp.flush()
        tmp.close()
        self.addCleanup(os.unlink, tmp.name)
        scanner = PluginSecurityScanner(tmp.name)
        report = scanner.scan()
        for check in report["checks"]:
            if check["name"] == "Suspicious Files":
                return check
        return {}

    def test_bandit_config_not_flagged_as_hidden(self):
        """.bandit must not appear in suspicious-files issues."""
        check = self._run_suspicious_check(
            {
                "myplugin/__init__.py": b"x = 1\n",
                "myplugin/.bandit": b"[bandit]\nskips = B311\n",
            }
        )
        hidden_files = [
            d["file"]
            for d in check.get("details", [])
            if d.get("rule_code") == "FILE_HIDDEN"
        ]
        self.assertFalse(
            any(".bandit" in f for f in hidden_files),
            f".bandit incorrectly flagged as hidden: {hidden_files}",
        )

    def test_secrets_baseline_not_flagged_as_hidden(self):
        """.secrets.baseline must not appear in suspicious-files issues."""
        check = self._run_suspicious_check(
            {
                "myplugin/__init__.py": b"x = 1\n",
                "myplugin/.secrets.baseline": b"{}",
            }
        )
        hidden_files = [
            d["file"]
            for d in check.get("details", [])
            if d.get("rule_code") == "FILE_HIDDEN"
        ]
        self.assertFalse(
            any(".secrets.baseline" in f for f in hidden_files),
            f".secrets.baseline incorrectly flagged as hidden: {hidden_files}",
        )

    def test_flake8_config_not_flagged_as_hidden(self):
        """.flake8 must not appear in suspicious-files issues."""
        check = self._run_suspicious_check(
            {
                "myplugin/__init__.py": b"x = 1\n",
                "myplugin/.flake8": b"[flake8]\nextend-ignore = E501\n",
            }
        )
        hidden_files = [
            d["file"]
            for d in check.get("details", [])
            if d.get("rule_code") == "FILE_HIDDEN"
        ]
        self.assertFalse(
            any(".flake8" in f for f in hidden_files),
            f".flake8 incorrectly flagged as hidden: {hidden_files}",
        )

    def test_unknown_hidden_file_still_flagged(self):
        """.env (not in allowlist) must still be flagged as hidden."""
        check = self._run_suspicious_check(
            {
                "myplugin/__init__.py": b"x = 1\n",
                "myplugin/.env": b"SECRET=abc\n",
            }
        )
        hidden_files = [
            d["file"]
            for d in check.get("details", [])
            if d.get("rule_code") == "FILE_HIDDEN"
        ]
        self.assertTrue(
            any(".env" in f for f in hidden_files),
            ".env should have been flagged as hidden",
        )


class ConfigFileValidationStatusTest(TestCase):
    """Tests for the validated_with_config validation status flow."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="cfguser", password="pass", email="cfg@test.com"
        )
        self.plugin, self.version = _make_plugin_version(
            self.user, VALIDATION_STATUS_VALIDATING
        )

    def _make_scan(self, critical_count=0, config_files=None):
        """Create a PluginVersionSecurityScan with optional config_files_detected."""
        return PluginVersionSecurityScan.objects.create(
            plugin_version=self.version,
            critical_count=critical_count,
            warning_count=0,
            passed_checks=5,
            total_checks=5,
            files_scanned=1,
            config_files_detected=config_files or [],
            scan_report={
                "summary": {
                    "total_checks": 5,
                    "passed": 5,
                    "failed": 0,
                    "critical": critical_count,
                    "warnings": 0,
                    "info": 0,
                    "files_scanned": 1,
                    "total_issues": 0,
                },
                "checks": [],
            },
        )

    def test_is_available_for_validated_with_config(self):
        """validated_with_config must be treated as available (not blocked)."""
        self.version.validation_status = VALIDATION_STATUS_VALIDATED_WITH_CONFIG
        self.version.save()
        self.version.refresh_from_db()
        self.assertTrue(self.version.is_available)

    @override_settings(DEBUG=True)
    @patch("plugins.tasks.run_security_scan.run_security_scan")
    def test_task_sets_validated_with_config_when_config_files_present(self, mock_scan):
        """Task must set validated_with_config when config files were detected."""
        scan = self._make_scan(critical_count=0, config_files=[".bandit"])
        mock_scan.return_value = scan

        run_security_scan_task(self.version.pk)

        self.version.refresh_from_db()
        self.assertEqual(
            self.version.validation_status, VALIDATION_STATUS_VALIDATED_WITH_CONFIG
        )

    @override_settings(DEBUG=True)
    @patch("plugins.tasks.run_security_scan.run_security_scan")
    def test_task_sets_validated_when_no_config_files(self, mock_scan):
        """Task must set validated (not validated_with_config) when no config files."""
        scan = self._make_scan(critical_count=0, config_files=[])
        mock_scan.return_value = scan

        run_security_scan_task(self.version.pk)

        self.version.refresh_from_db()
        self.assertEqual(self.version.validation_status, VALIDATION_STATUS_VALIDATED)

    @override_settings(DEBUG=True)
    @patch("plugins.tasks.run_security_scan.run_security_scan")
    def test_task_blocks_even_with_config_files_when_critical_issues(self, mock_scan):
        """Config files do not prevent blocking when critical issues are found."""
        scan = self._make_scan(critical_count=1, config_files=[".bandit"])
        mock_scan.return_value = scan

        run_security_scan_task(self.version.pk)

        self.version.refresh_from_db()
        self.assertEqual(self.version.validation_status, VALIDATION_STATUS_BLOCKED)

    def test_config_files_stored_in_scan_record(self):
        """config_files_detected field must persist the list correctly."""
        scan = self._make_scan(config_files=[".bandit", ".flake8"])
        scan.refresh_from_db()
        self.assertIn(".bandit", scan.config_files_detected)
        self.assertIn(".flake8", scan.config_files_detected)

    @patch("plugins.security_utils.PluginSecurityScanner")
    def test_run_security_scan_stores_config_files(self, MockScanner):
        """run_security_scan() must persist config_files from the report."""
        mock_report = {
            "summary": {
                "total_checks": 1,
                "passed": 1,
                "failed": 0,
                "critical": 0,
                "warnings": 0,
                "info": 0,
                "files_scanned": 1,
                "total_issues": 0,
            },
            "config_files": [".bandit"],
            "checks": [],
        }
        MockScanner.return_value.scan.return_value = mock_report
        self.version.package = MagicMock()
        self.version.package.path = "/tmp/fake.zip"

        result = run_security_scan(self.version)

        result.refresh_from_db()
        self.assertIn(".bandit", result.config_files_detected)
