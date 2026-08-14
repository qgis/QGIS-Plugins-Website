"""
Tests for plugins.middleware.HttpAuthMiddleware.

The middleware used to decode an Authorization header on every URL in the
site, authenticate against it, and log the user in on success. That made every
page a password oracle with no throttling, issued a session per successful RPC
call, and returned a 500 for any Authorization scheme it could not base64
decode.

It is now limited to the RPC endpoint, does not create a session, and ignores
malformed headers.
"""

import base64

from django.contrib.auth.models import AnonymousUser, User
from django.test import Client, RequestFactory, TestCase
from plugins.middleware import HttpAuthMiddleware

USERNAME = "rpc_user"
PASSWORD = "rpc-password-not-a-real-secret"


def _basic(username, password):
    raw = f"{username}:{password}".encode("utf8")
    return "Basic " + base64.b64encode(raw).decode("ascii")


class HttpAuthMiddlewareTest(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = User.objects.create_user(
            username=USERNAME, email="rpc@example.com", password=PASSWORD
        )

    def _run(self, request):
        """Run the middleware and report the user the view would see."""
        seen = {}

        def view(req):
            seen["user"] = getattr(req, "user", None)
            return "response"

        request.user = AnonymousUser()
        HttpAuthMiddleware(view)(request)
        return seen["user"]

    def test_valid_credentials_authenticate_on_the_rpc_path(self):
        request = self.factory.post(
            "/plugins/RPC2/", HTTP_AUTHORIZATION=_basic(USERNAME, PASSWORD)
        )
        self.assertEqual(self._run(request), self.user)

    def test_wrong_password_does_not_authenticate(self):
        request = self.factory.post(
            "/plugins/RPC2/", HTTP_AUTHORIZATION=_basic(USERNAME, "wrong")
        )
        self.assertTrue(self._run(request).is_anonymous)

    def test_credentials_are_ignored_outside_the_rpc_path(self):
        """The whole site used to accept Basic auth; only RPC2 may now."""
        for path in ["/", "/plugins/", "/admin/", "/accounts/login/"]:
            with self.subTest(path=path):
                request = self.factory.get(
                    path, HTTP_AUTHORIZATION=_basic(USERNAME, PASSWORD)
                )
                self.assertTrue(self._run(request).is_anonymous)

    def test_no_session_is_created(self):
        """RPC clients authenticate per call and never use the cookie."""
        request = self.factory.post(
            "/plugins/RPC2/", HTTP_AUTHORIZATION=_basic(USERNAME, PASSWORD)
        )
        request.session = {}
        self._run(request)
        self.assertEqual(dict(request.session), {})

    def test_malformed_headers_do_not_raise(self):
        """Anything undecodable is ignored rather than becoming a 500."""
        malformed = [
            "Basic !!!not-base64!!!",
            "Basic ",
            "Basic " + base64.b64encode(b"\xff\xfe").decode("ascii"),
            "Basic " + base64.b64encode(b"no-separator").decode("ascii"),
        ]
        for header in malformed:
            with self.subTest(header=header):
                request = self.factory.post("/plugins/RPC2/", HTTP_AUTHORIZATION=header)
                self.assertTrue(self._run(request).is_anonymous)

    def test_other_schemes_are_left_alone(self):
        """Bearer belongs to the token decorators; Token/Negotiate to nobody."""
        for header in ["Bearer abc.def.ghi", "Token abc", "Negotiate abc", ""]:
            with self.subTest(header=header):
                request = self.factory.post("/plugins/RPC2/", HTTP_AUTHORIZATION=header)
                self.assertTrue(self._run(request).is_anonymous)


class HttpAuthMiddlewareRequestTest(TestCase):
    """End to end through the real middleware stack."""

    def setUp(self):
        self.client = Client()
        User.objects.create_user(
            username=USERNAME, email="rpc@example.com", password=PASSWORD
        )

    def test_unparseable_authorization_header_is_not_a_500(self):
        """Previously binascii.Error escaped and returned a server error."""
        for header in ["Token abc", "Negotiate abc", "Basic !!!"]:
            with self.subTest(header=header):
                response = self.client.get("/", HTTP_AUTHORIZATION=header)
                self.assertLess(response.status_code, 500)

    def test_basic_auth_on_a_normal_page_does_not_log_in(self):
        response = self.client.get("/", HTTP_AUTHORIZATION=_basic(USERNAME, PASSWORD))
        self.assertLess(response.status_code, 500)
        self.assertNotIn("sessionid", response.cookies)


class RpcBasicAuthTest(TestCase):
    """The RPC endpoint must still authenticate, since that is why this exists.

    Nothing else in the suite exercises XML-RPC: upload_test.py and ws_test.py
    predate the test runner's test*.py discovery pattern and never run.
    """

    MAINTAINERS_CALL = (
        '<?xml version="1.0"?>'
        "<methodCall><methodName>plugin.maintainers</methodName>"
        "<params></params></methodCall>"
    )

    def setUp(self):
        self.client = Client()
        self.admin = User.objects.create_superuser(
            username="rpc_admin", email="admin@example.com", password=PASSWORD
        )

    def _call(self, **extra):
        return self.client.post(
            "/plugins/RPC2/",
            data=self.MAINTAINERS_CALL,
            content_type="text/xml",
            **extra,
        )

    def test_valid_credentials_reach_a_login_required_method(self):
        response = self._call(HTTP_AUTHORIZATION=_basic("rpc_admin", PASSWORD))
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b"<name>faultCode</name>", response.content)

    def test_anonymous_call_is_refused(self):
        """rpc4django answers a login_required method with a bare 403."""
        self.assertEqual(self._call().status_code, 403)

    def test_wrong_password_is_refused(self):
        response = self._call(HTTP_AUTHORIZATION=_basic("rpc_admin", "wrong"))
        self.assertEqual(response.status_code, 403)
