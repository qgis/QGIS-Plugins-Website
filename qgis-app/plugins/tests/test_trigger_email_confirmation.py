# -*- coding: utf-8 -*-
"""
Tests for automated email-confirmation triggers.

Covers:
  - check_and_send_confirmation task (sends / skips cases)
  - send_pending_email_confirmations periodic task (sweep, expiry, stats)
  - Plugin.save() email-change hook
  - version_approve() view hook
"""

import datetime
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import RequestFactory, TestCase
from django.utils import timezone
from plugins.models import Plugin, PluginEmailConfirmation, PluginVersion
from plugins.tasks.trigger_email_confirmation import (
    check_and_send_confirmation,
    send_pending_email_confirmations,
)

# ---------------------------------------------------------------------------
# Shared helpers (mirror test_email_confirmation.py conventions)
# ---------------------------------------------------------------------------


def make_plugin(creator: User, package_name: str, email: str, **kwargs) -> Plugin:
    return Plugin.objects.create(
        created_by=creator,
        package_name=package_name,
        name=package_name.replace("-", " ").title(),
        author="Test Author",
        email=email,
        repository="http://example.com",
        tracker="http://example.com",
        **kwargs,
    )


def make_approved_plugin(
    creator: User, package_name: str, email: str, **kwargs
) -> Plugin:
    plugin = make_plugin(creator, package_name, email, **kwargs)
    PluginVersion.objects.create(
        plugin=plugin,
        created_by=creator,
        min_qg_version="3.0.0",
        max_qg_version="3.99.99",
        version="1.0",
        approved=True,
        external_deps="",
    )
    return plugin


def make_confirmed_confirmation(
    email: str, plugins: list[Plugin]
) -> PluginEmailConfirmation:
    conf = PluginEmailConfirmation.objects.create(
        email=email,
        key=f"confirmed-{email}",
        expires_at=timezone.now() + datetime.timedelta(days=30),
        confirmed_at=timezone.now(),
    )
    conf.plugins.set(plugins)
    return conf


def make_expired_pending(email: str, plugins: list[Plugin]) -> PluginEmailConfirmation:
    conf = PluginEmailConfirmation.objects.create(
        email=email,
        key=f"expired-{email}",
        expires_at=timezone.now() - datetime.timedelta(days=1),
    )
    conf.plugins.set(plugins)
    return conf


class SetupMixin:
    fixtures = ["fixtures/auth.json"]

    def setUp(self):
        self.creator = User.objects.get(id=2)


# ---------------------------------------------------------------------------
# check_and_send_confirmation
# ---------------------------------------------------------------------------


class TestCheckAndSendConfirmation(SetupMixin, TestCase):
    @patch("plugins.tasks.trigger_email_confirmation.send_confirmation_email")
    def test_sends_when_approved_and_unconfirmed(self, mock_send):
        plugin = make_approved_plugin(self.creator, "tce-plugin-a", "a@example.com")
        check_and_send_confirmation(plugin.pk)
        mock_send.assert_called_once()
        conf = mock_send.call_args[0][0]
        self.assertEqual(conf.email, "a@example.com")

    @patch("plugins.tasks.trigger_email_confirmation.send_confirmation_email")
    def test_skips_if_already_confirmed(self, mock_send):
        plugin = make_approved_plugin(self.creator, "tce-plugin-b", "b@example.com")
        make_confirmed_confirmation("b@example.com", [plugin])
        check_and_send_confirmation(plugin.pk)
        mock_send.assert_not_called()

    @patch("plugins.tasks.trigger_email_confirmation.send_confirmation_email")
    def test_skips_if_no_validated_or_approved_version(self, mock_send):
        plugin = make_plugin(self.creator, "tce-plugin-c", "c@example.com")
        # No version at all — neither approved nor available
        check_and_send_confirmation(plugin.pk)
        mock_send.assert_not_called()

    @patch("plugins.tasks.trigger_email_confirmation.send_confirmation_email")
    def test_sends_for_validated_but_not_yet_approved(self, mock_send):
        # Confirmation must go out before manual approval, so a validated
        # (available) but unapproved version is enough to trigger the send.
        plugin = make_plugin(self.creator, "tce-plugin-f", "f@example.com")
        PluginVersion.objects.create(
            plugin=plugin,
            created_by=self.creator,
            min_qg_version="3.0.0",
            max_qg_version="3.99.99",
            version="1.0",
            approved=False,
            external_deps="",
            validation_status="validated",
        )
        check_and_send_confirmation(plugin.pk)
        mock_send.assert_called_once()

    @patch("plugins.tasks.trigger_email_confirmation.send_confirmation_email")
    def test_skips_if_email_empty(self, mock_send):
        plugin = make_approved_plugin(self.creator, "tce-plugin-d", "")
        check_and_send_confirmation(plugin.pk)
        mock_send.assert_not_called()

    @patch("plugins.tasks.trigger_email_confirmation.send_confirmation_email")
    def test_plugin_not_found_is_silent(self, mock_send):
        # Must not raise
        check_and_send_confirmation(99999)
        mock_send.assert_not_called()

    @patch(
        "plugins.tasks.trigger_email_confirmation.send_confirmation_email",
        side_effect=RuntimeError("SMTP down"),
    )
    def test_does_not_raise_on_send_error(self, _mock_send):
        plugin = make_approved_plugin(self.creator, "tce-plugin-e", "e@example.com")
        # Must not propagate the exception
        check_and_send_confirmation(plugin.pk)


# ---------------------------------------------------------------------------
# send_pending_email_confirmations
# ---------------------------------------------------------------------------


class TestSendPendingEmailConfirmations(SetupMixin, TestCase):
    @patch("plugins.tasks.trigger_email_confirmation.send_confirmation_email")
    def test_sends_to_approved_plugins_with_unconfirmed_email(self, mock_send):
        make_approved_plugin(self.creator, "spe-plugin-a", "sweep@example.com")
        result = send_pending_email_confirmations()
        mock_send.assert_called_once()
        self.assertEqual(result["sent"], 1)
        self.assertEqual(result["skipped"], 0)

    @patch("plugins.tasks.trigger_email_confirmation.send_confirmation_email")
    def test_skips_already_confirmed_email(self, mock_send):
        plugin = make_approved_plugin(self.creator, "spe-plugin-b", "conf@example.com")
        make_confirmed_confirmation("conf@example.com", [plugin])
        result = send_pending_email_confirmations()
        mock_send.assert_not_called()
        self.assertEqual(result["sent"], 0)
        self.assertEqual(result["skipped"], 1)

    @patch("plugins.tasks.trigger_email_confirmation.send_confirmation_email")
    def test_deletes_expired_pending_before_sweep(self, mock_send):
        plugin = make_approved_plugin(self.creator, "spe-plugin-c", "exp@example.com")
        expired = make_expired_pending("exp@example.com", [plugin])
        expired_pk = expired.pk
        result = send_pending_email_confirmations()
        # Expired token was deleted and a fresh one sent
        self.assertFalse(PluginEmailConfirmation.objects.filter(pk=expired_pk).exists())
        mock_send.assert_called_once()
        self.assertEqual(result["sent"], 1)

    @patch("plugins.tasks.trigger_email_confirmation.send_confirmation_email")
    def test_returns_stats_dict(self, mock_send):
        make_approved_plugin(self.creator, "spe-plugin-d", "stats@example.com")
        result = send_pending_email_confirmations()
        self.assertIn("sent", result)
        self.assertIn("skipped", result)
        self.assertIn("errors", result)

    @patch("plugins.tasks.trigger_email_confirmation.send_confirmation_email")
    def test_groups_plugins_by_shared_email(self, mock_send):
        email = "shared@example.com"
        make_approved_plugin(self.creator, "spe-shared-1", email)
        make_approved_plugin(self.creator, "spe-shared-2", email)
        result = send_pending_email_confirmations()
        # Both plugins share one email → one send call
        mock_send.assert_called_once()
        self.assertEqual(result["sent"], 1)

    @patch(
        "plugins.tasks.trigger_email_confirmation.send_confirmation_email",
        side_effect=Exception("SMTP error"),
    )
    def test_records_send_error_in_stats(self, _mock_send):
        make_approved_plugin(self.creator, "spe-plugin-err", "err@example.com")
        result = send_pending_email_confirmations()
        self.assertEqual(result["errors"], 1)
        self.assertEqual(result["sent"], 0)


# ---------------------------------------------------------------------------
# Plugin.save() email-change hook
# ---------------------------------------------------------------------------


class TestEmailChangeHook(SetupMixin, TestCase):
    def test_task_queued_when_email_changes(self):
        plugin = make_approved_plugin(self.creator, "ech-plugin-a", "old@example.com")
        with (
            patch(
                "plugins.tasks.trigger_email_confirmation.check_and_send_confirmation.delay"
            ) as mock_delay,
            self.captureOnCommitCallbacks(execute=True),
        ):
            plugin.email = "new@example.com"
            plugin.save()
        mock_delay.assert_called_once_with(plugin.pk)

    def test_task_not_queued_when_email_unchanged(self):
        plugin = make_approved_plugin(self.creator, "ech-plugin-b", "same@example.com")
        with (
            patch(
                "plugins.tasks.trigger_email_confirmation.check_and_send_confirmation.delay"
            ) as mock_delay,
            self.captureOnCommitCallbacks(execute=True),
        ):
            plugin.name = "Updated Name"
            plugin.save()
        mock_delay.assert_not_called()

    def test_task_not_queued_when_email_cleared(self):
        plugin = make_approved_plugin(self.creator, "ech-plugin-c", "clear@example.com")
        with (
            patch(
                "plugins.tasks.trigger_email_confirmation.check_and_send_confirmation.delay"
            ) as mock_delay,
            self.captureOnCommitCallbacks(execute=True),
        ):
            plugin.email = ""
            plugin.save()
        mock_delay.assert_not_called()


# ---------------------------------------------------------------------------
# version_approve() email-verification gate
# ---------------------------------------------------------------------------


class TestVersionApproveGate(SetupMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.staff = User.objects.get(id=1)  # fixture superuser
        self.factory = RequestFactory()

    def _make_approvable_version(self, package_name, email):
        plugin = make_plugin(self.creator, package_name, email)
        version = PluginVersion.objects.create(
            plugin=plugin,
            created_by=self.creator,
            min_qg_version="3.0.0",
            max_qg_version="3.99.99",
            version="1.0",
            approved=False,
            external_deps="",
            validation_status="validated",
        )
        return plugin, version

    def _approve(self, plugin, version):
        from plugins.views import version_approve

        request = self.factory.post(
            f"/plugins/{plugin.package_name}/{version.version}/approve/"
        )
        request.user = self.staff
        with patch("plugins.views.plugin_approve_notify"):
            return version_approve(request, plugin.package_name, version.version)

    def test_blocks_approval_when_email_unconfirmed(self):
        plugin, version = self._make_approvable_version(
            "vag-plugin-a", "vag-a@example.com"
        )
        self._approve(plugin, version)
        version.refresh_from_db()
        self.assertFalse(version.approved)

    def test_allows_approval_when_email_confirmed(self):
        plugin, version = self._make_approvable_version(
            "vag-plugin-b", "vag-b@example.com"
        )
        make_confirmed_confirmation("vag-b@example.com", [plugin])
        self._approve(plugin, version)
        version.refresh_from_db()
        self.assertTrue(version.approved)


# ---------------------------------------------------------------------------
# Plugin model helpers
# ---------------------------------------------------------------------------


class TestPluginEmailHelpers(SetupMixin, TestCase):
    def test_is_email_confirmed_true_when_confirmed(self):
        plugin = make_approved_plugin(self.creator, "peh-plugin-a", "peh-a@example.com")
        make_confirmed_confirmation("peh-a@example.com", [plugin])
        self.assertTrue(plugin.is_email_confirmed)

    def test_is_email_confirmed_false_when_only_pending(self):
        plugin = make_approved_plugin(self.creator, "peh-plugin-b", "peh-b@example.com")
        make_expired_pending("peh-b@example.com", [plugin])
        self.assertFalse(plugin.is_email_confirmed)

    def test_is_email_confirmed_false_when_no_email(self):
        plugin = make_approved_plugin(self.creator, "peh-plugin-c", "")
        self.assertFalse(plugin.is_email_confirmed)

    def test_first_published_on_is_earliest_approved_version(self):
        plugin = make_plugin(self.creator, "peh-plugin-d", "peh-d@example.com")
        early = PluginVersion.objects.create(
            plugin=plugin,
            created_by=self.creator,
            min_qg_version="3.0.0",
            max_qg_version="3.99.99",
            version="1.0",
            approved=True,
            external_deps="",
        )
        PluginVersion.objects.create(
            plugin=plugin,
            created_by=self.creator,
            min_qg_version="3.0.0",
            max_qg_version="3.99.99",
            version="2.0",
            approved=True,
            external_deps="",
        )
        self.assertEqual(plugin.first_published_on, early.created_on)

    def test_first_published_on_none_when_unapproved(self):
        plugin = make_plugin(self.creator, "peh-plugin-e", "peh-e@example.com")
        PluginVersion.objects.create(
            plugin=plugin,
            created_by=self.creator,
            min_qg_version="3.0.0",
            max_qg_version="3.99.99",
            version="1.0",
            approved=False,
            external_deps="",
        )
        self.assertIsNone(plugin.first_published_on)


# ---------------------------------------------------------------------------
# Annual anniversary re-verification
# ---------------------------------------------------------------------------


class TestAnniversaryReverification(SetupMixin, TestCase):
    def _set_first_published(self, plugin, when):
        # created_on is auto_now_add; set it directly on the approved version.
        plugin.pluginversion_set.update(created_on=when)

    @staticmethod
    def _anniversary_today():
        # A datetime in a prior year sharing today's month/day.
        now_dt = timezone.now()
        return now_dt.replace(year=now_dt.year - 1, hour=12, minute=0, second=0, microsecond=0)

    @patch("plugins.tasks.trigger_annual_reverification.send_confirmation_email")
    def test_reverifies_even_already_confirmed_and_keeps_history(self, mock_send):
        from plugins.tasks.trigger_annual_reverification import (
            send_anniversary_reverifications,
        )

        plugin = make_approved_plugin(self.creator, "anv-plugin-a", "anv-a@example.com")
        self._set_first_published(plugin, self._anniversary_today())
        old = make_confirmed_confirmation("anv-a@example.com", [plugin])

        result = send_anniversary_reverifications()

        mock_send.assert_called_once()
        self.assertEqual(result["sent"], 1)
        # Old confirmed record kept as history; a new pending record now exists.
        self.assertTrue(
            PluginEmailConfirmation.objects.filter(pk=old.pk).exists()
        )
        self.assertEqual(
            PluginEmailConfirmation.objects.filter(email="anv-a@example.com").count(),
            2,
        )

    @patch("plugins.tasks.trigger_annual_reverification.send_confirmation_email")
    def test_skips_non_anniversary_plugins(self, mock_send):
        from plugins.tasks.trigger_annual_reverification import (
            send_anniversary_reverifications,
        )

        plugin = make_approved_plugin(self.creator, "anv-plugin-b", "anv-b@example.com")
        not_today = timezone.now() - datetime.timedelta(days=100)
        self._set_first_published(plugin, not_today)

        result = send_anniversary_reverifications()

        mock_send.assert_not_called()
        self.assertEqual(result["sent"], 0)

    @patch("plugins.tasks.trigger_annual_reverification.send_confirmation_email")
    def test_does_not_resend_twice_in_same_day(self, mock_send):
        from plugins.tasks.trigger_annual_reverification import (
            send_anniversary_reverifications,
        )

        plugin = make_approved_plugin(self.creator, "anv-plugin-c", "anv-c@example.com")
        self._set_first_published(plugin, self._anniversary_today())

        send_anniversary_reverifications()
        result = send_anniversary_reverifications()

        # Second run finds the pending record created today and skips.
        self.assertEqual(mock_send.call_count, 1)
        self.assertEqual(result["sent"], 0)
        self.assertEqual(result["skipped"], 1)
