# -*- coding: utf-8 -*-
"""
Unit tests for the plugin email confirmation system.

Covers:
  - PluginEmailConfirmation model (create_for_email, confirm, properties)
  - Plugin.save() side-effect when email changes
  - confirm_plugin_email view (all status branches)
  - send_confirmation_email helper (email content and addressing)
  - send_email_confirmation management command (filtering, skipping, resend, errors)
  - PluginEmailConfirmationError model
"""

import datetime
from io import StringIO
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from plugins.models import (
    Plugin,
    PluginEmailConfirmation,
    PluginEmailConfirmationError,
    PluginVersion,
)

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def make_plugin(creator, package_name, email, **kwargs):
    """Create a minimal Plugin instance, bypassing form validation."""
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


def make_approved_plugin(creator, package_name, email, **kwargs):
    """Create a Plugin with one approved version (required for approved_objects)."""
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


def make_pending_confirmation(email, plugins, key="test-key-pending"):
    """Create an unexpired, unconfirmed PluginEmailConfirmation."""
    conf = PluginEmailConfirmation.objects.create(
        email=email,
        key=key,
        expires_at=timezone.now() + datetime.timedelta(days=30),
    )
    conf.plugins.set(plugins)
    return conf


def make_confirmed_confirmation(email, plugins, key="test-key-confirmed"):
    """Create a confirmed PluginEmailConfirmation."""
    conf = PluginEmailConfirmation.objects.create(
        email=email,
        key=key,
        expires_at=timezone.now() + datetime.timedelta(days=30),
        confirmed_at=timezone.now(),
    )
    conf.plugins.set(plugins)
    return conf


def make_expired_confirmation(email, plugins, key="test-key-expired"):
    """Create an expired, unconfirmed PluginEmailConfirmation."""
    conf = PluginEmailConfirmation.objects.create(
        email=email,
        key=key,
        expires_at=timezone.now() - datetime.timedelta(days=1),
    )
    conf.plugins.set(plugins)
    return conf


class SetupMixin:
    """Two plugins sharing one address, one plugin on a different address."""

    fixtures = ["fixtures/auth.json"]

    def setUp(self):
        self.creator = User.objects.get(id=2)
        self.plugin_a = make_plugin(self.creator, "ec-plugin-a", "author@example.com")
        self.plugin_b = make_plugin(self.creator, "ec-plugin-b", "author@example.com")
        self.plugin_other = make_plugin(
            self.creator, "ec-plugin-other", "other@example.com"
        )


# ---------------------------------------------------------------------------
# PluginEmailConfirmation.create_for_email
# ---------------------------------------------------------------------------


class TestCreateForEmail(SetupMixin, TestCase):

    def test_creates_new_confirmation(self):
        conf, created = PluginEmailConfirmation.create_for_email(
            "author@example.com", [self.plugin_a, self.plugin_b]
        )
        self.assertTrue(created)
        self.assertIsNotNone(conf)
        self.assertEqual(conf.email, "author@example.com")
        self.assertSetEqual(
            set(conf.plugins.values_list("pk", flat=True)),
            {self.plugin_a.pk, self.plugin_b.pk},
        )

    def test_filters_out_plugins_with_mismatched_email(self):
        """plugin_other has a different email and must be excluded."""
        conf, created = PluginEmailConfirmation.create_for_email(
            "author@example.com",
            [self.plugin_a, self.plugin_other],
        )
        self.assertTrue(created)
        self.assertIn(self.plugin_a, conf.plugins.all())
        self.assertNotIn(self.plugin_other, conf.plugins.all())

    def test_returns_none_when_no_valid_plugins(self):
        conf, created = PluginEmailConfirmation.create_for_email(
            "author@example.com",
            [self.plugin_other],  # wrong email
        )
        self.assertIsNone(conf)
        self.assertFalse(created)

    def test_returns_none_when_all_plugins_already_confirmed(self):
        make_confirmed_confirmation(
            "author@example.com", [self.plugin_a], key="already-confirmed-key"
        )
        conf, created = PluginEmailConfirmation.create_for_email(
            "author@example.com", [self.plugin_a]
        )
        self.assertIsNone(conf)
        self.assertFalse(created)

    def test_reuses_existing_unexpired_pending(self):
        first, _ = PluginEmailConfirmation.create_for_email(
            "author@example.com", [self.plugin_a]
        )
        # Second call: same email, add plugin_b
        second, created = PluginEmailConfirmation.create_for_email(
            "author@example.com", [self.plugin_a, self.plugin_b]
        )
        self.assertFalse(created)
        self.assertEqual(first.pk, second.pk)
        # M2M should be updated to include plugin_b
        self.assertIn(self.plugin_b, second.plugins.all())

    def test_creates_new_when_existing_is_expired(self):
        expired = make_expired_confirmation(
            "author@example.com", [self.plugin_a], key="expired-key-create"
        )
        conf, created = PluginEmailConfirmation.create_for_email(
            "author@example.com", [self.plugin_a]
        )
        self.assertTrue(created)
        self.assertNotEqual(conf.pk, expired.pk)

    def test_confirmed_email_skips_new_plugin(self):
        """Per-email: once an address is confirmed, a brand-new plugin using
        that address inherits the verified status — no new round is sent."""
        make_confirmed_confirmation(
            "author@example.com",
            [self.plugin_a, self.plugin_b],
            key="old-round-key",
        )
        new_plugin = make_plugin(self.creator, "ec-plugin-new", "author@example.com")
        conf, created = PluginEmailConfirmation.create_for_email(
            "author@example.com",
            [self.plugin_a, self.plugin_b, new_plugin],
        )
        self.assertIsNone(conf)
        self.assertFalse(created)
        # The new plugin is verified by virtue of the address being confirmed,
        # even though it was never linked to the confirmed record.
        self.assertTrue(new_plugin.is_email_confirmed)


# ---------------------------------------------------------------------------
# PluginEmailConfirmation properties and confirm()
# ---------------------------------------------------------------------------


class TestPluginEmailConfirmationModel(SetupMixin, TestCase):

    def test_is_confirmed_false_before_confirm(self):
        conf, _ = PluginEmailConfirmation.create_for_email(
            "author@example.com", [self.plugin_a]
        )
        self.assertFalse(conf.is_confirmed)

    def test_is_confirmed_true_after_confirm(self):
        conf, _ = PluginEmailConfirmation.create_for_email(
            "author@example.com", [self.plugin_a]
        )
        conf.confirm()
        conf.refresh_from_db()
        self.assertTrue(conf.is_confirmed)
        self.assertIsNotNone(conf.confirmed_at)

    def test_is_expired_false_for_future_expiry(self):
        conf, _ = PluginEmailConfirmation.create_for_email(
            "author@example.com", [self.plugin_a]
        )
        self.assertFalse(conf.is_expired)

    def test_is_expired_true_for_past_expiry(self):
        conf = make_expired_confirmation(
            "author@example.com", [self.plugin_a], key="expired-prop-key"
        )
        self.assertTrue(conf.is_expired)

    def test_confirmed_record_is_not_expired(self):
        """A confirmed record must never be reported as expired."""
        conf = make_expired_confirmation(
            "author@example.com", [self.plugin_a], key="expired-but-confirmed"
        )
        conf.confirmed_at = timezone.now()
        conf.save(update_fields=["confirmed_at"])
        self.assertFalse(conf.is_expired)

    def test_str_contains_email_and_status(self):
        conf, _ = PluginEmailConfirmation.create_for_email(
            "author@example.com", [self.plugin_a]
        )
        s = str(conf)
        self.assertIn("author@example.com", s)
        self.assertIn("pending", s)

    def test_str_confirmed_status(self):
        conf, _ = PluginEmailConfirmation.create_for_email(
            "author@example.com", [self.plugin_a]
        )
        conf.confirm()
        self.assertIn("confirmed", str(conf))


# ---------------------------------------------------------------------------
# Plugin.save() side-effect: email change invalidates pending confirmations
# ---------------------------------------------------------------------------


class TestEmailChangeCleansConfirmations(SetupMixin, TestCase):

    def test_email_change_removes_plugin_from_pending_confirmation(self):
        conf = make_pending_confirmation(
            "author@example.com",
            [self.plugin_a, self.plugin_b],
            key="cleanup-pending-key",
        )
        self.plugin_a.email = "new@example.com"
        self.plugin_a.save()

        conf.refresh_from_db()
        self.assertNotIn(self.plugin_a, conf.plugins.all())
        self.assertIn(self.plugin_b, conf.plugins.all())

    def test_empty_confirmation_deleted_after_email_change(self):
        conf = make_pending_confirmation(
            "author@example.com", [self.plugin_a], key="cleanup-delete-key"
        )
        conf_pk = conf.pk
        self.plugin_a.email = "new@example.com"
        self.plugin_a.save()

        self.assertFalse(PluginEmailConfirmation.objects.filter(pk=conf_pk).exists())

    def test_email_change_does_not_affect_confirmed_records(self):
        conf = make_confirmed_confirmation(
            "author@example.com", [self.plugin_a], key="cleanup-confirmed-key"
        )
        conf_pk = conf.pk
        self.plugin_a.email = "new@example.com"
        self.plugin_a.save()

        # Confirmed records are historical — must survive email changes
        self.assertTrue(PluginEmailConfirmation.objects.filter(pk=conf_pk).exists())

    def test_no_change_when_email_unchanged(self):
        conf = make_pending_confirmation(
            "author@example.com", [self.plugin_a], key="no-change-key"
        )
        original_count = conf.plugins.count()
        # Save without changing email
        self.plugin_a.save()
        conf.refresh_from_db()
        self.assertEqual(conf.plugins.count(), original_count)


# ---------------------------------------------------------------------------
# View: confirm_plugin_email
# ---------------------------------------------------------------------------


class TestConfirmPluginEmailView(SetupMixin, TestCase):

    def _url(self, key):
        return reverse("confirm_plugin_email", args=[key])

    def test_valid_key_returns_200_and_confirmed_status(self):
        conf, _ = PluginEmailConfirmation.create_for_email(
            "author@example.com", [self.plugin_a]
        )
        response = self.client.get(self._url(conf.key))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["status"], "confirmed")

    def test_valid_key_sets_confirmed_at(self):
        conf, _ = PluginEmailConfirmation.create_for_email(
            "author@example.com", [self.plugin_a]
        )
        self.client.get(self._url(conf.key))
        conf.refresh_from_db()
        self.assertIsNotNone(conf.confirmed_at)

    def test_already_confirmed_returns_already_confirmed_status(self):
        conf = make_confirmed_confirmation(
            "author@example.com", [self.plugin_a], key="view-already-key"
        )
        response = self.client.get(self._url(conf.key))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["status"], "already_confirmed")

    def test_already_confirmed_does_not_update_confirmed_at(self):
        original_confirmed_at = timezone.now() - datetime.timedelta(hours=1)
        conf = PluginEmailConfirmation.objects.create(
            email="author@example.com",
            key="view-already-at-key",
            expires_at=timezone.now() + datetime.timedelta(days=30),
            confirmed_at=original_confirmed_at,
        )
        conf.plugins.set([self.plugin_a])
        self.client.get(self._url(conf.key))
        conf.refresh_from_db()
        self.assertEqual(conf.confirmed_at, original_confirmed_at)

    def test_expired_key_returns_expired_status(self):
        conf = make_expired_confirmation(
            "author@example.com", [self.plugin_a], key="view-expired-key"
        )
        response = self.client.get(self._url(conf.key))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["status"], "expired")

    def test_invalid_key_returns_404(self):
        response = self.client.get(self._url("this-key-does-not-exist"))
        self.assertEqual(response.status_code, 404)

    def test_no_login_required(self):
        """Unauthenticated users must be able to follow the link."""
        self.client.logout()
        conf, _ = PluginEmailConfirmation.create_for_email(
            "author@example.com", [self.plugin_a]
        )
        response = self.client.get(self._url(conf.key))
        self.assertEqual(response.status_code, 200)

    def test_context_contains_plugin_names(self):
        conf, _ = PluginEmailConfirmation.create_for_email(
            "author@example.com", [self.plugin_a, self.plugin_b]
        )
        response = self.client.get(self._url(conf.key))
        self.assertIn(self.plugin_a.name, response.context["plugin_names"])
        self.assertIn(self.plugin_b.name, response.context["plugin_names"])


# ---------------------------------------------------------------------------
# Helper: send_confirmation_email
# ---------------------------------------------------------------------------


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class TestSendConfirmationEmailHelper(SetupMixin, TestCase):

    def setUp(self):
        super().setUp()
        mail.outbox = []

    def _send(self, plugins):
        from plugins.views import send_confirmation_email

        conf, _ = PluginEmailConfirmation.create_for_email(
            "author@example.com", plugins
        )
        send_confirmation_email(conf)
        return conf

    def test_sends_one_email(self):
        self._send([self.plugin_a])
        self.assertEqual(len(mail.outbox), 1)

    def test_email_addressed_to_confirmation_address(self):
        self._send([self.plugin_a])
        self.assertIn("author@example.com", mail.outbox[0].to)

    def test_singular_subject_contains_plugin_name(self):
        self._send([self.plugin_a])
        self.assertIn(self.plugin_a.name, mail.outbox[0].subject)

    def test_plural_subject_contains_plugin_count(self):
        self._send([self.plugin_a, self.plugin_b])
        self.assertIn("2", mail.outbox[0].subject)

    def test_email_body_contains_confirmation_key(self):
        conf = self._send([self.plugin_a])
        self.assertIn(conf.key, mail.outbox[0].body)

    def test_html_alternative_attached(self):
        self._send([self.plugin_a])
        alternatives = mail.outbox[0].alternatives
        content_types = [ct for _, ct in alternatives]
        self.assertIn("text/html", content_types)

    def test_expiry_includes_timezone_label(self):
        # Regression: strftime("%Z") is blank for naive datetimes (USE_TZ=False),
        # which rendered "expires on 2026-07-10 02:37 " with no zone.
        self._send([self.plugin_a])
        self.assertRegex(mail.outbox[0].body, r"\d{4}-\d{2}-\d{2} \d{2}:\d{2} [A-Za-z]")


# ---------------------------------------------------------------------------
# Helper: notify_editors_of_pending_confirmation (editor-notification backstop)
# ---------------------------------------------------------------------------


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class TestEditorNotificationBackstop(SetupMixin, TestCase):
    """
    The tokenless heads-up sent to plugin editors alongside the confirmation
    email so a shared/unmonitored contact mailbox doesn't silently stall.
    """

    def setUp(self):
        super().setUp()
        mail.outbox = []

    def _send(self, plugins, address="author@example.com"):
        from plugins.views import send_confirmation_email

        conf, _ = PluginEmailConfirmation.create_for_email(address, plugins)
        send_confirmation_email(conf)
        return conf

    def _editor_messages(self):
        """Messages other than the token email (which goes to the metadata address)."""
        return [m for m in mail.outbox if "author@example.com" not in m.to]

    def test_no_extra_email_when_only_editor_has_empty_email(self):
        # The fixture creator (id=2) has an empty email and is the sole editor,
        # so the backstop is a no-op — only the token email is sent.
        self._send([self.plugin_a])
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(self._editor_messages(), [])

    def test_notifies_editor_with_distinct_email(self):
        alice = User.objects.create_user("alice", "alice@org.com", "pw")
        self.plugin_a.owners.add(alice)
        self._send([self.plugin_a])
        editor_msgs = self._editor_messages()
        self.assertEqual(len(editor_msgs), 1)
        self.assertEqual(editor_msgs[0].to, ["alice@org.com"])

    def test_notification_is_tokenless(self):
        alice = User.objects.create_user("alice", "alice@org.com", "pw")
        self.plugin_a.owners.add(alice)
        conf = self._send([self.plugin_a])
        msg = self._editor_messages()[0]
        haystack = msg.body + " ".join(body for body, _ in msg.alternatives)
        # Neither the token nor the direct confirmation link may appear.
        self.assertNotIn(conf.key, haystack)
        self.assertIn("text/html", [ct for _, ct in msg.alternatives])

    def test_editor_whose_email_matches_metadata_is_not_pinged(self):
        # An editor whose account email equals the address being verified already
        # received the token email — no redundant heads-up.
        same = User.objects.create_user("same", "author@example.com", "pw")
        self.plugin_a.owners.add(same)
        self._send([self.plugin_a])
        self.assertEqual(self._editor_messages(), [])

    def test_per_editor_scoping_across_shared_address(self):
        # plugin_a (Alice) and plugin_b (Carol) share author@example.com, but
        # each editor must only hear about the plugin they actually manage.
        alice = User.objects.create_user("alice", "alice@org.com", "pw")
        carol = User.objects.create_user("carol", "carol@org.com", "pw")
        self.plugin_a.owners.add(alice)
        self.plugin_b.owners.add(carol)
        self._send([self.plugin_a, self.plugin_b])

        by_addr = {m.to[0]: m for m in self._editor_messages()}
        self.assertEqual(set(by_addr), {"alice@org.com", "carol@org.com"})

        self.assertIn(self.plugin_a.name, by_addr["alice@org.com"].body)
        self.assertNotIn(self.plugin_b.name, by_addr["alice@org.com"].body)

        self.assertIn(self.plugin_b.name, by_addr["carol@org.com"].body)
        self.assertNotIn(self.plugin_a.name, by_addr["carol@org.com"].body)

    def test_editor_of_multiple_plugins_gets_single_email(self):
        bob = User.objects.create_user("bob", "bob@org.com", "pw")
        self.plugin_a.owners.add(bob)
        self.plugin_b.owners.add(bob)
        self._send([self.plugin_a, self.plugin_b])
        bob_msgs = [m for m in self._editor_messages() if m.to == ["bob@org.com"]]
        self.assertEqual(len(bob_msgs), 1)
        self.assertIn(self.plugin_a.name, bob_msgs[0].body)
        self.assertIn(self.plugin_b.name, bob_msgs[0].body)

    def test_backstop_failure_does_not_break_primary_email(self):
        from plugins.views import send_confirmation_email

        conf, _ = PluginEmailConfirmation.create_for_email(
            "author@example.com", [self.plugin_a]
        )
        with patch(
            "plugins.email_utils.notify_editors_of_pending_confirmation",
            side_effect=Exception("boom"),
        ):
            send_confirmation_email(conf)  # must not raise

        # The primary confirmation email still went out.
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("author@example.com", mail.outbox[0].to)


# ---------------------------------------------------------------------------
# Management command: send_email_confirmation
# ---------------------------------------------------------------------------

MOCK_SEND = (
    "plugins.management.commands.send_email_confirmation.send_confirmation_email"
)


class TestSendEmailConfirmationCommand(SetupMixin, TestCase):
    """Tests for the management command.

    SetupMixin plugins have no approved versions so they are invisible to
    Plugin.approved_objects — tests that exercise the command create their own
    plugins via make_approved_plugin().
    """

    def _call(self, **kwargs):
        from django.core.management import call_command

        out = StringIO()
        err = StringIO()
        call_command("send_email_confirmation", stdout=out, stderr=err, **kwargs)
        return out.getvalue(), err.getvalue()

    @patch(MOCK_SEND)
    def test_dry_run_sends_no_emails_and_no_db_records(self, mock_send):
        make_approved_plugin(self.creator, "cmd-dryrun-a", "dry@example.com")
        self._call(dry_run=True)
        mock_send.assert_not_called()
        self.assertFalse(PluginEmailConfirmation.objects.exists())

    @patch(MOCK_SEND)
    def test_sends_one_email_per_unique_address(self, mock_send):
        make_approved_plugin(self.creator, "cmd-multi-a", "addr1@example.com")
        make_approved_plugin(self.creator, "cmd-multi-b", "addr1@example.com")
        make_approved_plugin(self.creator, "cmd-multi-c", "addr2@example.com")
        self._call()
        self.assertEqual(mock_send.call_count, 2)

    @patch(MOCK_SEND)
    def test_email_filter_restricts_to_given_address(self, mock_send):
        make_approved_plugin(self.creator, "cmd-filter-a", "filter@example.com")
        make_approved_plugin(self.creator, "cmd-filter-b", "noise@example.com")
        self._call(email="filter@example.com")
        self.assertEqual(mock_send.call_count, 1)
        sent_conf = mock_send.call_args[0][0]
        self.assertEqual(sent_conf.email, "filter@example.com")

    def test_email_filter_invalid_address_writes_to_stderr(self):
        _, err = self._call(email="nobody@example.com")
        self.assertIn("nobody@example.com", err)

    @patch(MOCK_SEND)
    def test_skips_address_where_all_plugins_confirmed(self, mock_send):
        plugin = make_approved_plugin(
            self.creator, "cmd-skip-conf", "confirmed@example.com"
        )
        make_confirmed_confirmation(
            "confirmed@example.com", [plugin], key="cmd-confirmed-key"
        )
        self._call(email="confirmed@example.com")
        mock_send.assert_not_called()

    @patch(MOCK_SEND)
    def test_skips_address_with_existing_pending_confirmation(self, mock_send):
        plugin = make_approved_plugin(
            self.creator, "cmd-skip-pend", "pending@example.com"
        )
        PluginEmailConfirmation.create_for_email("pending@example.com", [plugin])
        self._call(email="pending@example.com")
        mock_send.assert_not_called()

    @patch(MOCK_SEND)
    def test_resend_sends_even_when_already_confirmed(self, mock_send):
        plugin = make_approved_plugin(
            self.creator, "cmd-resend-a", "resend@example.com"
        )
        make_confirmed_confirmation(
            "resend@example.com", [plugin], key="cmd-resend-key"
        )
        self._call(email="resend@example.com", resend=True)
        mock_send.assert_called_once()

    @patch(MOCK_SEND)
    def test_resend_sends_even_when_pending_exists(self, mock_send):
        plugin = make_approved_plugin(
            self.creator, "cmd-resend-b", "resend2@example.com"
        )
        PluginEmailConfirmation.create_for_email("resend2@example.com", [plugin])
        self._call(email="resend2@example.com", resend=True)
        mock_send.assert_called_once()

    @patch(MOCK_SEND, side_effect=Exception("SMTP timeout"))
    def test_send_failure_creates_error_record(self, mock_send):
        make_approved_plugin(self.creator, "cmd-err-a", "error@example.com")
        self._call(email="error@example.com")
        error = PluginEmailConfirmationError.objects.filter(
            email="error@example.com"
        ).first()
        self.assertIsNotNone(error)
        self.assertIn("SMTP timeout", error.error)
        self.assertIn("cmd-err-a", error.plugins)

    @patch(MOCK_SEND, side_effect=Exception("SMTP timeout"))
    def test_send_failure_reported_in_stdout(self, mock_send):
        make_approved_plugin(self.creator, "cmd-err-b", "error2@example.com")
        out, _ = self._call(email="error2@example.com")
        self.assertIn("Error", out)


# ---------------------------------------------------------------------------
# PluginEmailConfirmationError model
# ---------------------------------------------------------------------------


class TestPluginEmailConfirmationError(TestCase):

    def test_create_and_retrieve(self):
        err = PluginEmailConfirmationError.objects.create(
            email="fail@example.com",
            plugins="plugin-x, plugin-y",
            error="Connection refused",
        )
        self.assertIsNotNone(err.occurred_at)
        self.assertEqual(
            PluginEmailConfirmationError.objects.filter(
                email="fail@example.com"
            ).count(),
            1,
        )

    def test_str_contains_email(self):
        err = PluginEmailConfirmationError.objects.create(
            email="fail@example.com",
            plugins="plugin-x",
            error="Timeout",
        )
        self.assertIn("fail@example.com", str(err))

    def test_ordering_newest_first(self):
        PluginEmailConfirmationError.objects.create(
            email="a@example.com", plugins="p1", error="err1"
        )
        PluginEmailConfirmationError.objects.create(
            email="b@example.com", plugins="p2", error="err2"
        )
        records = list(PluginEmailConfirmationError.objects.all())
        # Newer record (b) should appear first
        self.assertEqual(records[0].email, "b@example.com")


# ---------------------------------------------------------------------------
# View: resend_plugin_email_confirmation
# ---------------------------------------------------------------------------


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class TestResendPluginEmailConfirmationView(SetupMixin, TestCase):

    def _url(self, package_name):
        return reverse("plugin_resend_email_confirmation", args=[package_name])

    def setUp(self):
        # Override SetupMixin to use approved plugins — the resend view queries
        # Plugin.approved_objects, so unapproved plugins would be invisible to it.
        self.creator = User.objects.get(id=2)
        self.staff_user = User.objects.get(id=3)  # staff, non-superuser
        self.admin_user = User.objects.get(id=1)  # superuser
        self.editor_user = User.objects.get(id=2)  # creator / editor, non-staff
        self.plugin_a = make_approved_plugin(
            self.creator, "ec-plugin-a", "author@example.com"
        )
        self.plugin_b = make_approved_plugin(
            self.creator, "ec-plugin-b", "author@example.com"
        )
        self.plugin_other = make_approved_plugin(
            self.creator, "ec-plugin-other", "other@example.com"
        )
        mail.outbox = []

    # ---- access control ---------------------------------------------------

    def test_anonymous_redirected_to_login(self):
        self.client.logout()
        response = self.client.post(self._url(self.plugin_a.package_name))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/", response["Location"])

    def test_editor_can_resend(self):
        """A plugin editor (owner/creator) may resend from the detail page."""
        self.client.force_login(self.editor_user)
        response = self.client.post(self._url(self.plugin_a.package_name))
        self.assertRedirects(
            response,
            reverse("plugin_detail", args=[self.plugin_a.package_name]),
            fetch_redirect_response=False,
        )
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("author@example.com", mail.outbox[0].to)

    def test_unrelated_user_gets_permission_deny(self):
        """A logged-in user who is neither editor nor staff is refused."""
        stranger = User.objects.create_user("stranger", "stranger@org.com", "pw")
        self.client.force_login(stranger)
        response = self.client.post(self._url(self.plugin_a.package_name))
        # Returns the permission-deny template (200 with error page)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "plugins/plugin_permission_deny.html")
        self.assertEqual(len(mail.outbox), 0)

    def test_get_not_allowed(self):
        """The resend endpoint only accepts POST."""
        self.client.force_login(self.staff_user)
        response = self.client.get(self._url(self.plugin_a.package_name))
        self.assertEqual(response.status_code, 405)

    def test_staff_user_redirects_to_detail_on_success(self):
        self.client.force_login(self.staff_user)
        response = self.client.post(self._url(self.plugin_a.package_name))
        self.assertRedirects(
            response,
            reverse("plugin_detail", args=[self.plugin_a.package_name]),
            fetch_redirect_response=False,
        )

    def test_superuser_redirects_to_detail_on_success(self):
        self.client.force_login(self.admin_user)
        response = self.client.post(self._url(self.plugin_a.package_name))
        self.assertRedirects(
            response,
            reverse("plugin_detail", args=[self.plugin_a.package_name]),
            fetch_redirect_response=False,
        )

    def test_unknown_package_name_returns_404(self):
        self.client.force_login(self.staff_user)
        response = self.client.post(self._url("no-such-plugin"))
        self.assertEqual(response.status_code, 404)

    # ---- email sending ----------------------------------------------------

    def test_sends_email_to_plugin_address(self):
        self.client.force_login(self.staff_user)
        self.client.post(self._url(self.plugin_a.package_name))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("author@example.com", mail.outbox[0].to)

    def test_resend_sends_email_when_pending_exists(self):
        """An existing pending confirmation is deleted and a fresh one is sent."""
        old_conf = make_pending_confirmation(
            "author@example.com",
            [self.plugin_a],
            key="resend-old-key",
        )
        # Backdate past the resend cooldown so the request is not throttled
        # (sent_at uses auto_now_add, so it must be updated at the DB level).
        PluginEmailConfirmation.objects.filter(pk=old_conf.pk).update(
            sent_at=timezone.now() - datetime.timedelta(hours=1)
        )
        self.client.force_login(self.staff_user)
        self.client.post(self._url(self.plugin_a.package_name))
        # Old pending record must be gone
        self.assertFalse(
            PluginEmailConfirmation.objects.filter(pk=old_conf.pk).exists()
        )
        # One new email sent
        self.assertEqual(len(mail.outbox), 1)

    def test_resend_creates_new_confirmation_when_expired(self):
        """An expired confirmation is replaced with a fresh one."""
        expired = make_expired_confirmation(
            "author@example.com",
            [self.plugin_a],
            key="resend-expired-key",
        )
        # An expired confirmation was, by definition, sent long ago; align
        # sent_at so the cooldown does not throttle this resend.
        PluginEmailConfirmation.objects.filter(pk=expired.pk).update(
            sent_at=timezone.now() - datetime.timedelta(days=31)
        )
        self.client.force_login(self.staff_user)
        self.client.post(self._url(self.plugin_a.package_name))
        self.assertFalse(PluginEmailConfirmation.objects.filter(pk=expired.pk).exists())
        new_conf = PluginEmailConfirmation.objects.filter(
            email="author@example.com", confirmed_at__isnull=True
        ).first()
        self.assertIsNotNone(new_conf)
        self.assertNotEqual(new_conf.pk, expired.pk)

    def test_resend_covers_all_plugins_with_same_email(self):
        """All plugins sharing the email are included in the new confirmation."""
        self.client.force_login(self.staff_user)
        self.client.post(self._url(self.plugin_a.package_name))
        new_conf = PluginEmailConfirmation.objects.filter(
            email="author@example.com", confirmed_at__isnull=True
        ).first()
        self.assertIsNotNone(new_conf)
        plugin_pks = set(new_conf.plugins.values_list("pk", flat=True))
        # Both plugin_a and plugin_b share author@example.com
        self.assertIn(self.plugin_a.pk, plugin_pks)
        self.assertIn(self.plugin_b.pk, plugin_pks)

    def test_confirmed_record_not_deleted_by_resend(self):
        """Resend must not delete already-confirmed records."""
        confirmed = make_confirmed_confirmation(
            "author@example.com",
            [self.plugin_a],
            key="resend-confirmed-key",
        )
        self.client.force_login(self.staff_user)
        self.client.post(self._url(self.plugin_a.package_name))
        # Confirmed record must still exist
        self.assertTrue(
            PluginEmailConfirmation.objects.filter(pk=confirmed.pk).exists()
        )

    # ---- detail page button -----------------------------------------------

    def test_resend_button_shown_on_detail_page_for_editor(self):
        """The plugin detail page exposes the resend form to an editor."""
        self.client.force_login(self.editor_user)
        response = self.client.get(
            reverse("plugin_detail", args=[self.plugin_a.package_name])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self._url(self.plugin_a.package_name))

    def test_resend_button_hidden_from_anonymous(self):
        """Anonymous visitors never see the resend form."""
        self.client.logout()
        response = self.client.get(
            reverse("plugin_detail", args=[self.plugin_a.package_name])
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, self._url(self.plugin_a.package_name))

    # ---- rate limiting ----------------------------------------------------

    def test_second_resend_is_throttled(self):
        """A second resend within the cooldown window sends no new email."""
        self.client.force_login(self.staff_user)
        self.client.post(self._url(self.plugin_a.package_name))
        self.assertEqual(len(mail.outbox), 1)

        # Immediate retry: blocked by the per-address cooldown.
        self.client.post(self._url(self.plugin_a.package_name))
        self.assertEqual(len(mail.outbox), 1)

    def test_resend_allowed_again_after_cooldown(self):
        """Once the cooldown has elapsed, a fresh resend is permitted."""
        self.client.force_login(self.staff_user)
        self.client.post(self._url(self.plugin_a.package_name))
        self.assertEqual(len(mail.outbox), 1)

        # Age the pending confirmation past the cooldown window.
        PluginEmailConfirmation.objects.filter(
            email="author@example.com", confirmed_at__isnull=True
        ).update(sent_at=timezone.now() - datetime.timedelta(hours=1))

        self.client.post(self._url(self.plugin_a.package_name))
        self.assertEqual(len(mail.outbox), 2)

    def test_throttle_is_per_address_not_per_plugin(self):
        """Resending plugin_b is throttled by plugin_a's recent send (same email)."""
        self.client.force_login(self.staff_user)
        self.client.post(self._url(self.plugin_a.package_name))
        self.assertEqual(len(mail.outbox), 1)

        # plugin_b shares author@example.com, so it inherits the cooldown.
        self.client.post(self._url(self.plugin_b.package_name))
        self.assertEqual(len(mail.outbox), 1)


# ---------------------------------------------------------------------------
# plugin_email_token_confirm view
# ---------------------------------------------------------------------------


class TestPluginEmailTokenConfirmView(SetupMixin, TestCase):

    def _url(self, package_name):
        return reverse("plugin_email_token_confirm", args=[package_name])

    def setUp(self):
        super().setUp()
        self.creator = User.objects.get(id=2)  # editor / non-staff
        self.staff_user = User.objects.get(id=3)
        self.other_user = User.objects.create_user(
            username="other_token_user", password="pass"
        )

    # ---- access control ---------------------------------------------------

    def test_anonymous_redirected_to_login(self):
        self.client.logout()
        response = self.client.get(self._url(self.plugin_a.package_name))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/", response["Location"])

    def test_non_editor_gets_permission_deny(self):
        """A logged-in user who is not an editor/staff is denied."""
        self.client.force_login(self.other_user)
        response = self.client.get(self._url(self.plugin_a.package_name))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "plugins/plugin_permission_deny.html")

    def test_editor_can_see_form(self):
        make_pending_confirmation(
            "author@example.com", [self.plugin_a], key="tok-pending"
        )
        self.client.force_login(self.creator)
        response = self.client.get(self._url(self.plugin_a.package_name))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "plugins/plugin_email_token_confirm.html")
        self.assertContains(response, 'name="token"')

    def test_staff_can_see_form(self):
        make_pending_confirmation(
            "author@example.com", [self.plugin_a], key="tok-staff-pending"
        )
        self.client.force_login(self.staff_user)
        response = self.client.get(self._url(self.plugin_a.package_name))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "plugins/plugin_email_token_confirm.html")
        self.assertContains(response, 'name="token"')

    def test_no_confirmation_shows_info_not_form(self):
        """Without any confirmation record the form is not shown."""
        self.client.force_login(self.creator)
        response = self.client.get(self._url(self.plugin_a.package_name))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'name="token"')

    def test_expired_confirmation_shows_info_not_form(self):
        """An expired confirmation hides the form and shows an expiry message."""
        make_expired_confirmation(
            "author@example.com", [self.plugin_a], key="tok-expired"
        )
        self.client.force_login(self.creator)
        response = self.client.get(self._url(self.plugin_a.package_name))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'name="token"')

    def test_confirmed_shows_info_not_form(self):
        """An already-confirmed record hides the form."""
        make_confirmed_confirmation(
            "author@example.com", [self.plugin_a], key="tok-confirmed"
        )
        self.client.force_login(self.creator)
        response = self.client.get(self._url(self.plugin_a.package_name))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'name="token"')

    def test_unknown_package_name_returns_404(self):
        self.client.force_login(self.creator)
        response = self.client.get(self._url("no-such-plugin"))
        self.assertEqual(response.status_code, 404)

    # ---- POST behaviour ---------------------------------------------------

    def test_post_with_valid_token_redirects_to_confirm_view(self):
        """Submitting a token redirects to the confirm_plugin_email URL."""
        self.client.force_login(self.creator)
        token = "somesecrettoken"
        response = self.client.post(
            self._url(self.plugin_a.package_name),
            {"token": token},
        )
        expected_url = reverse("confirm_plugin_email", args=[token])
        self.assertRedirects(response, expected_url, fetch_redirect_response=False)

    def test_post_with_token_leading_trailing_whitespace_is_stripped(self):
        """Tokens with surrounding whitespace are stripped before redirect."""
        self.client.force_login(self.creator)
        token = "  cleantoken  "
        response = self.client.post(
            self._url(self.plugin_a.package_name),
            {"token": token},
        )
        expected_url = reverse("confirm_plugin_email", args=["cleantoken"])
        self.assertRedirects(response, expected_url, fetch_redirect_response=False)

    def test_post_with_empty_token_re_renders_form_with_error(self):
        """Submitting an empty token stays on the form and shows an error."""
        self.client.force_login(self.creator)
        response = self.client.post(
            self._url(self.plugin_a.package_name),
            {"token": ""},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "plugins/plugin_email_token_confirm.html")
        self.assertIn("error", response.context)

    def test_post_with_whitespace_only_token_re_renders_form_with_error(self):
        """Whitespace-only token is treated as empty."""
        self.client.force_login(self.creator)
        response = self.client.post(
            self._url(self.plugin_a.package_name),
            {"token": "   "},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "plugins/plugin_email_token_confirm.html")
        self.assertIn("error", response.context)
