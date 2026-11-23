"""
Tests for blocking an author.

A blocked author must lose web sessions, RPC access and plugin tokens. Staff
confirm the block on its own page and can unapprove the author's maintained
plugins there. Those plugins then stay out of the review queue.

Several tests use AllowAllUsersModelBackend. Like the LDAP backend used in
production, it authenticates inactive users, so the tests exercise our own
checks rather than ModelBackend's.
"""

import base64
import datetime

from django.contrib.auth.models import User
from django.test import Client, RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from plugins.decorators import validate_plugin_token
from plugins.models import (
    Plugin,
    PluginEmailConfirmation,
    PluginOutstandingToken,
    PluginVersion,
)
from rest_framework_simplejwt.settings import api_settings
from rest_framework_simplejwt.token_blacklist.models import OutstandingToken
from rest_framework_simplejwt.tokens import RefreshToken

ALLOW_INACTIVE = ["django.contrib.auth.backends.AllowAllUsersModelBackend"]
PASSWORD = "block-test-password-not-a-secret"


def _make_plugin(maintainer: User, package_name: str, approved: bool) -> Plugin:
    plugin = Plugin.objects.create(
        created_by=maintainer,
        repository="http://example.com",
        tracker="http://example.com",
        package_name=package_name,
        name=package_name,
        about="A plugin used by the author blocking tests",
        author="Plugin author",
        email=f"{package_name}@example.com",
    )
    PluginVersion.objects.create(
        plugin=plugin,
        created_by=maintainer,
        min_qg_version="0.0.0",
        max_qg_version="99.99.99",
        version="0.1",
        approved=approved,
        external_deps="test",
    )
    return plugin


def _basic(username: str, password: str) -> str:
    raw = f"{username}:{password}".encode("utf8")
    return "Basic " + base64.b64encode(raw).decode("ascii")


def _block(user: User) -> None:
    user.is_active = False
    user.save()


class UserBlockConfirmationTest(TestCase):
    def setUp(self) -> None:
        self.staff = User.objects.create_user(
            username="block_staff", password=PASSWORD, is_staff=True
        )
        self.author = User.objects.create_user(username="block_author")
        self.other = User.objects.create_user(username="block_other")
        self.maintained = _make_plugin(self.author, "maintained-plugin", True)
        self.co_owned = _make_plugin(self.other, "co-owned-plugin", True)
        self.co_owned.owners.add(self.author)
        self.url = reverse("user_block", args=[self.author.username])
        self.client.force_login(self.staff)

    def test_non_staff_cannot_open_or_submit_the_page(self) -> None:
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(self.url).status_code, 302)
        self.assertEqual(self.client.post(self.url).status_code, 302)
        self.author.refresh_from_db()
        self.assertTrue(self.author.is_active)

    def test_get_shows_the_confirmation_without_blocking(self) -> None:
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "plugins/user_block_confirm.html")
        self.assertContains(response, 'name="unapprove_plugins"')
        self.assertContains(response, "maintained-plugin")
        self.assertNotContains(response, "co-owned-plugin")
        self.author.refresh_from_db()
        self.assertTrue(self.author.is_active)

    def test_checkbox_is_hidden_when_the_author_maintains_nothing(self) -> None:
        User.objects.create_user(username="nobody")
        response = self.client.get(reverse("user_block", args=["nobody"]))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'name="unapprove_plugins"')
        self.assertContains(response, "does not maintain any plugin")

    def test_post_blocks_and_keeps_plugins_approved_by_default(self) -> None:
        response = self.client.post(self.url)
        self.assertRedirects(
            response,
            reverse("user_details", args=[self.author.username]),
            fetch_redirect_response=False,
        )
        self.author.refresh_from_db()
        self.assertFalse(self.author.is_active)
        self.assertTrue(PluginVersion.objects.get(plugin=self.maintained).approved)

    def test_post_with_checkbox_unapproves_only_maintained_plugins(self) -> None:
        self.client.post(self.url, {"unapprove_plugins": "1"})
        self.author.refresh_from_db()
        self.assertFalse(self.author.is_active)
        self.assertFalse(PluginVersion.objects.get(plugin=self.maintained).approved)
        self.assertTrue(PluginVersion.objects.get(plugin=self.co_owned).approved)

    def test_staff_accounts_cannot_be_blocked(self) -> None:
        target = User.objects.create_user(username="other_staff", is_staff=True)
        url = reverse("user_block", args=[target.username])
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.post(url).status_code, 404)

    def test_manage_endpoint_sends_staff_to_the_confirmation(self) -> None:
        response = self.client.post(
            reverse("user_permissions_manage", args=[self.author.username]),
            {"user_block": "1"},
        )
        self.assertRedirects(response, self.url, fetch_redirect_response=False)
        self.author.refresh_from_db()
        self.assertTrue(self.author.is_active)


@override_settings(AUTHENTICATION_BACKENDS=ALLOW_INACTIVE)
class BlockedUserSessionTest(TestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(username="session_user")
        self.client.force_login(self.user)

    def test_active_user_keeps_the_session(self) -> None:
        self.assertEqual(self.client.get(reverse("my_plugins")).status_code, 200)

    def test_blocked_user_is_logged_out_on_the_next_request(self) -> None:
        _block(self.user)
        response = self.client.get(reverse("my_plugins"))
        self.assertEqual(response.status_code, 302)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_blocked_user_cannot_reach_the_upload_form(self) -> None:
        _block(self.user)
        response = self.client.get(reverse("plugin_upload"))
        self.assertEqual(response.status_code, 302)


@override_settings(AUTHENTICATION_BACKENDS=ALLOW_INACTIVE)
class BlockedUserRpcTest(TestCase):
    UPLOAD_CALL = (
        '<?xml version="1.0"?>'
        "<methodCall><methodName>plugin.upload</methodName>"
        "<params><param><value><base64>AAAA</base64></value></param></params>"
        "</methodCall>"
    )

    def setUp(self) -> None:
        self.client = Client()
        self.user = User.objects.create_user(username="rpc_author", password=PASSWORD)

    def _upload(self):
        return self.client.post(
            "/plugins/RPC2/",
            data=self.UPLOAD_CALL,
            content_type="text/xml",
            HTTP_AUTHORIZATION=_basic("rpc_author", PASSWORD),
        )

    def test_active_user_reaches_the_upload_method(self) -> None:
        """The bogus package gets a fault, which proves the call got past login."""
        self.assertEqual(self._upload().status_code, 200)

    def test_blocked_user_is_refused(self) -> None:
        _block(self.user)
        self.assertEqual(self._upload().status_code, 403)


class BlockedUserTokenTest(TestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(username="token_author")
        self.plugin = _make_plugin(self.user, "token-plugin", True)
        refresh = RefreshToken.for_user(self.user)
        refresh["plugin_id"] = self.plugin.pk
        outstanding = OutstandingToken.objects.get(jti=refresh[api_settings.JTI_CLAIM])
        PluginOutstandingToken.objects.create(plugin=self.plugin, token=outstanding)
        refresh["refresh_jti"] = refresh[api_settings.JTI_CLAIM]
        self.header = f"Bearer {refresh.access_token}"

    def _validate(self) -> bool:
        request = RequestFactory().post("/", HTTP_AUTHORIZATION=self.header)
        return validate_plugin_token(request, self.plugin)

    def test_token_of_an_active_owner_is_valid(self) -> None:
        self.assertTrue(self._validate())

    def test_token_of_a_blocked_owner_is_rejected(self) -> None:
        _block(self.user)
        self.assertFalse(self._validate())

    def test_blocked_owner_cannot_upload_a_version(self) -> None:
        _block(self.user)
        response = Client(HTTP_AUTHORIZATION=self.header).post(
            reverse("version_create_api", args=[self.plugin.package_name])
        )
        self.assertEqual(response.status_code, 403)


class BlockedMaintainerReviewQueueTest(TestCase):
    def setUp(self) -> None:
        self.maintainer = User.objects.create_user(username="queue_maintainer")
        self.plugin = _make_plugin(self.maintainer, "queue-plugin", False)
        PluginEmailConfirmation.objects.create(
            email=self.plugin.email,
            key="queue-plugin-key",
            expires_at=timezone.now() + datetime.timedelta(days=30),
            confirmed_at=timezone.now(),
        )

    def _in_queues(self) -> tuple[bool, bool]:
        return (
            Plugin.unapproved_objects.filter(pk=self.plugin.pk).exists(),
            Plugin.feedback_pending_objects.filter(pk=self.plugin.pk).exists(),
        )

    def test_plugin_of_an_active_maintainer_is_in_the_queue(self) -> None:
        self.assertEqual(self._in_queues(), (True, True))

    def test_plugin_of_a_blocked_maintainer_leaves_the_queue(self) -> None:
        _block(self.maintainer)
        self.assertEqual(self._in_queues(), (False, False))

    def test_plugin_returns_to_the_queue_after_unblocking(self) -> None:
        _block(self.maintainer)
        self.maintainer.is_active = True
        self.maintainer.save()
        self.assertEqual(self._in_queues(), (True, True))

    def test_blocked_co_owner_does_not_hide_the_plugin(self) -> None:
        co_owner = User.objects.create_user(username="queue_co_owner")
        self.plugin.owners.add(co_owner)
        _block(co_owner)
        self.assertEqual(self._in_queues(), (True, True))
