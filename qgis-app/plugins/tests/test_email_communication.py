# -*- coding: utf-8 -*-
"""
Tests for the superuser-only email communication tool (issue #340).

Covers:
  - plugin_email_communicate view: superuser-only access + POST enqueues
  - get_communication_recipients: confirmed contacts + collaborators
  - send_email_communication task: BCC batching, record update, DEBUG redirect
"""

from unittest.mock import patch

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from plugins.models import PluginEmailCommunication, PluginEmailConfirmation
from plugins.tasks.send_email_communication import (
    get_communication_recipients,
    send_email_communication,
)
from plugins.tests.test_email_confirmation import (
    make_approved_plugin,
    make_confirmed_confirmation,
)

# ---------------------------------------------------------------------------
# View: access control + POST
# ---------------------------------------------------------------------------


class TestEmailCommunicateView(TestCase):

    fixtures = ["fixtures/auth.json"]

    def setUp(self):
        self.url = reverse("plugin_email_communicate")
        self.superuser = User.objects.get(id=1)  # admin, superuser
        self.staff_user = User.objects.get(id=3)  # staff, non-superuser

    def test_anonymous_is_redirected(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 302)

    def test_staff_non_superuser_is_redirected(self):
        self.client.force_login(self.staff_user)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 302)

    def test_superuser_sees_form(self):
        self.client.force_login(self.superuser)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)

    @patch("plugins.views.send_email_communication.delay")
    def test_superuser_post_creates_record_and_enqueues(self, mock_delay):
        self.client.force_login(self.superuser)
        resp = self.client.post(
            self.url, {"subject": "Hello authors", "body": "Some news."}
        )
        self.assertEqual(resp.status_code, 302)
        comm = PluginEmailCommunication.objects.get()
        self.assertEqual(comm.subject, "Hello authors")
        self.assertEqual(comm.status, PluginEmailCommunication.STATUS_QUEUED)
        self.assertEqual(comm.created_by, self.superuser)
        mock_delay.assert_called_once_with(comm.pk)

    @patch("plugins.views.send_email_communication.delay")
    def test_invalid_post_does_not_create_or_enqueue(self, mock_delay):
        self.client.force_login(self.superuser)
        resp = self.client.post(self.url, {"subject": "", "body": ""})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(PluginEmailCommunication.objects.count(), 0)
        mock_delay.assert_not_called()


# ---------------------------------------------------------------------------
# Recipient helper
# ---------------------------------------------------------------------------


class TestCommunicationRecipients(TestCase):

    fixtures = ["fixtures/auth.json"]

    def setUp(self):
        self.creator = User.objects.get(id=2)  # empty email

    def test_includes_confirmed_address_and_collaborators(self):
        plugin = make_approved_plugin(self.creator, "comm-a", "contact@org.com")
        owner = User.objects.create_user("owner1", "owner1@org.com", "pw")
        plugin.owners.add(owner)
        make_confirmed_confirmation("contact@org.com", [plugin], key="comm-a-key")

        lower = {r.lower() for r in get_communication_recipients()}
        self.assertIn("contact@org.com", lower)
        self.assertIn("owner1@org.com", lower)
        # creator (id=2) has an empty email -> never included
        self.assertNotIn("", lower)

    def test_excludes_unconfirmed_plugins(self):
        plugin = make_approved_plugin(self.creator, "comm-unconf", "unconf@org.com")
        PluginEmailConfirmation.create_for_email("unconf@org.com", [plugin])  # pending
        self.assertEqual(get_communication_recipients(), [])

    def test_excludes_deleted_plugins(self):
        plugin = make_approved_plugin(self.creator, "comm-del", "del@org.com")
        make_confirmed_confirmation("del@org.com", [plugin], key="comm-del-key")
        plugin.is_deleted = True
        plugin.save()
        self.assertEqual(get_communication_recipients(), [])

    def test_dedupes_collaborator_equal_to_contact(self):
        owner = User.objects.create_user("dup", "dup@org.com", "pw")
        plugin = make_approved_plugin(owner, "comm-dup", "dup@org.com")
        make_confirmed_confirmation("dup@org.com", [plugin], key="comm-dup-key")
        recipients = [r.lower() for r in get_communication_recipients()]
        self.assertEqual(recipients.count("dup@org.com"), 1)

    def test_splits_comma_separated_contact_address(self):
        plugin = make_approved_plugin(self.creator, "comm-multi", "a@org.com,b@org.com")
        make_confirmed_confirmation(
            "a@org.com,b@org.com", [plugin], key="comm-multi-key"
        )
        lower = {r.lower() for r in get_communication_recipients()}
        self.assertIn("a@org.com", lower)
        self.assertIn("b@org.com", lower)


# ---------------------------------------------------------------------------
# Celery task
# ---------------------------------------------------------------------------


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class TestSendEmailCommunicationTask(TestCase):

    fixtures = ["fixtures/auth.json"]

    def setUp(self):
        self.creator = User.objects.get(id=2)
        mail.outbox = []

    def _make_comm(self):
        return PluginEmailCommunication.objects.create(
            subject="News",
            body="Body",
            status=PluginEmailCommunication.STATUS_QUEUED,
        )

    def test_sends_bcc_and_updates_record(self):
        plugin = make_approved_plugin(self.creator, "task-a", "c1@org.com")
        owner = User.objects.create_user("o1", "o1@org.com", "pw")
        plugin.owners.add(owner)
        make_confirmed_confirmation("c1@org.com", [plugin], key="task-a-key")

        comm = self._make_comm()
        send_email_communication(comm.pk)

        self.assertEqual(len(mail.outbox), 1)
        self.assertSetEqual(set(mail.outbox[0].bcc), {"c1@org.com", "o1@org.com"})
        # Plain-text only — no HTML alternative attached.
        self.assertEqual(mail.outbox[0].content_subtype, "plain")
        self.assertEqual(getattr(mail.outbox[0], "alternatives", []), [])
        comm.refresh_from_db()
        self.assertEqual(comm.status, PluginEmailCommunication.STATUS_SENT)
        self.assertEqual(comm.recipient_count, 2)
        self.assertIsNotNone(comm.sent_at)

    @override_settings(EMAIL_COMMUNICATION_BATCH_SIZE=50)
    @patch("plugins.tasks.send_email_communication.get_communication_recipients")
    def test_batches_bcc_recipients(self, mock_recipients):
        addrs = [f"u{i}@org.com" for i in range(250)]
        mock_recipients.return_value = addrs
        comm = self._make_comm()
        send_email_communication(comm.pk)
        # Cap of 50 total recipients minus the single To leaves 49 BCC per
        # message: 250 / 49 -> 6 messages (49*5 + 5).
        self.assertEqual(len(mail.outbox), 6)
        for msg in mail.outbox:
            # To + Bcc must never exceed the provider cap.
            self.assertLessEqual(len(msg.to) + len(msg.bcc), 50)
        sent = [addr for msg in mail.outbox for addr in msg.bcc]
        self.assertEqual(sent, addrs)  # every address once, in order
        comm.refresh_from_db()
        self.assertEqual(comm.recipient_count, 250)

    @override_settings(DEBUG=True, DEVELOPER_EMAILS="dev@x.com")
    def test_debug_redirects_to_developer_emails(self):
        plugin = make_approved_plugin(self.creator, "task-dbg", "real@org.com")
        make_confirmed_confirmation("real@org.com", [plugin], key="task-dbg-key")
        comm = self._make_comm()
        send_email_communication(comm.pk)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].bcc, ["dev@x.com"])
        self.assertNotIn("real@org.com", mail.outbox[0].bcc)


# ---------------------------------------------------------------------------
# List view: access, search, filter, sort, pagination
# ---------------------------------------------------------------------------


class TestEmailCommunicationListView(TestCase):

    fixtures = ["fixtures/auth.json"]

    def setUp(self):
        self.url = reverse("plugin_email_communication_list")
        self.superuser = User.objects.get(id=1)
        self.staff_user = User.objects.get(id=3)

    def _make(self, subject, **kwargs):
        return PluginEmailCommunication.objects.create(
            subject=subject,
            body=kwargs.pop("body", "body"),
            created_by=kwargs.pop("created_by", self.superuser),
            status=kwargs.pop("status", PluginEmailCommunication.STATUS_SENT),
            **kwargs,
        )

    def test_anonymous_is_redirected(self):
        self.assertEqual(self.client.get(self.url).status_code, 302)

    def test_staff_non_superuser_is_redirected(self):
        self.client.force_login(self.staff_user)
        self.assertEqual(self.client.get(self.url).status_code, 302)

    def test_superuser_sees_list_with_author(self):
        self._make("First announcement")
        self.client.force_login(self.superuser)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "First announcement")
        self.assertContains(resp, self.superuser.username)

    def test_search_filters_by_subject(self):
        self._make("Security advisory")
        self._make("Holiday schedule")
        self.client.force_login(self.superuser)
        resp = self.client.get(self.url, {"q": "security"})
        self.assertContains(resp, "Security advisory")
        self.assertNotContains(resp, "Holiday schedule")

    def test_status_filter(self):
        self._make("Sentnews", status=PluginEmailCommunication.STATUS_SENT)
        self._make("Failednews", status=PluginEmailCommunication.STATUS_FAILED)
        self.client.force_login(self.superuser)
        resp = self.client.get(
            self.url, {"status": PluginEmailCommunication.STATUS_FAILED}
        )
        self.assertContains(resp, "Failednews")
        self.assertNotContains(resp, "Sentnews")

    def test_pagination(self):
        self._make("Comm A")
        self._make("Comm B")
        self.client.force_login(self.superuser)
        resp = self.client.get(self.url, {"per_page": 1})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.context["is_paginated"])
        self.assertEqual(resp.context["paginator"].num_pages, 2)

    def test_sort_by_subject_ascending(self):
        self._make("Bravo")
        self._make("Alpha")
        self.client.force_login(self.superuser)
        resp = self.client.get(self.url, {"sort": "subject", "order": "asc"})
        subjects = [c.subject for c in resp.context["page_obj"]]
        self.assertEqual(subjects, ["Alpha", "Bravo"])


# ---------------------------------------------------------------------------
# Detail view: access + content
# ---------------------------------------------------------------------------


class TestEmailCommunicationDetailView(TestCase):

    fixtures = ["fixtures/auth.json"]

    def setUp(self):
        self.superuser = User.objects.get(id=1)
        self.staff_user = User.objects.get(id=3)
        self.comm = PluginEmailCommunication.objects.create(
            subject="Detailed subject",
            body="The full secret body text.",
            created_by=self.superuser,
            status=PluginEmailCommunication.STATUS_SENT,
            recipient_count=3,
        )
        self.url = reverse("plugin_email_communication_detail", args=[self.comm.pk])

    def test_anonymous_is_redirected(self):
        self.assertEqual(self.client.get(self.url).status_code, 302)

    def test_staff_non_superuser_is_redirected(self):
        self.client.force_login(self.staff_user)
        self.assertEqual(self.client.get(self.url).status_code, 302)

    def test_superuser_sees_full_content(self):
        self.client.force_login(self.superuser)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Detailed subject")
        self.assertContains(resp, "The full secret body text.")

    def test_unknown_pk_returns_404(self):
        self.client.force_login(self.superuser)
        resp = self.client.get(
            reverse("plugin_email_communication_detail", args=[999999])
        )
        self.assertEqual(resp.status_code, 404)


# ---------------------------------------------------------------------------
# Resend action
# ---------------------------------------------------------------------------


class TestEmailCommunicationResend(TestCase):

    fixtures = ["fixtures/auth.json"]

    def setUp(self):
        self.superuser = User.objects.get(id=1)
        self.staff_user = User.objects.get(id=3)

    def _make(self, status):
        return PluginEmailCommunication.objects.create(
            subject="Retry me",
            body="body",
            created_by=self.superuser,
            status=status,
            error="boom",
        )

    def _url(self, pk):
        return reverse("plugin_email_communication_resend", args=[pk])

    def test_get_not_allowed(self):
        comm = self._make(PluginEmailCommunication.STATUS_FAILED)
        self.client.force_login(self.superuser)
        self.assertEqual(self.client.get(self._url(comm.pk)).status_code, 405)

    def test_staff_non_superuser_is_redirected(self):
        comm = self._make(PluginEmailCommunication.STATUS_FAILED)
        self.client.force_login(self.staff_user)
        self.assertEqual(self.client.post(self._url(comm.pk)).status_code, 302)

    @patch("plugins.views.send_email_communication.delay")
    def test_failed_communication_is_requeued(self, mock_delay):
        comm = self._make(PluginEmailCommunication.STATUS_FAILED)
        self.client.force_login(self.superuser)
        resp = self.client.post(self._url(comm.pk))
        self.assertEqual(resp.status_code, 302)
        comm.refresh_from_db()
        self.assertEqual(comm.status, PluginEmailCommunication.STATUS_QUEUED)
        self.assertEqual(comm.error, "")
        mock_delay.assert_called_once_with(comm.pk)

    @patch("plugins.views.send_email_communication.delay")
    def test_non_failed_communication_is_not_requeued(self, mock_delay):
        comm = self._make(PluginEmailCommunication.STATUS_SENT)
        self.client.force_login(self.superuser)
        resp = self.client.post(self._url(comm.pk))
        self.assertEqual(resp.status_code, 302)
        comm.refresh_from_db()
        self.assertEqual(comm.status, PluginEmailCommunication.STATUS_SENT)
        mock_delay.assert_not_called()
