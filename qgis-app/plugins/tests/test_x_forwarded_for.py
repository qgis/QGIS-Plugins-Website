from django.test import RequestFactory, TestCase, override_settings
from middleware import XForwardedForMiddleware


class XForwardedForMiddlewareTest(TestCase):
    """X-Forwarded-For is client supplied and must not be trusted by default."""

    def setUp(self):
        self.factory = RequestFactory()

    def _remote_addr_seen_by_view(self, request):
        seen = {}

        def view(req):
            seen["remote_addr"] = req.META.get("REMOTE_ADDR")
            return "response"

        XForwardedForMiddleware(view)(request)
        return seen["remote_addr"]

    @override_settings(TRUSTED_PROXY_DEPTH=0)
    def test_forged_header_is_ignored_by_default(self):
        request = self.factory.get(
            "/", REMOTE_ADDR="10.0.0.1", HTTP_X_FORWARDED_FOR="1.2.3.4"
        )
        self.assertEqual(self._remote_addr_seen_by_view(request), "10.0.0.1")

    @override_settings(TRUSTED_PROXY_DEPTH=0)
    def test_spoofed_chain_cannot_displace_peer_address(self):
        request = self.factory.get(
            "/",
            REMOTE_ADDR="10.0.0.1",
            HTTP_X_FORWARDED_FOR="1.2.3.4, 5.6.7.8, 9.10.11.12",
        )
        self.assertEqual(self._remote_addr_seen_by_view(request), "10.0.0.1")

    @override_settings(TRUSTED_PROXY_DEPTH=1)
    def test_one_trusted_proxy_reads_rightmost_entry(self):
        # Our proxy appends the address it saw, so the rightmost entry is the
        # real peer and everything left of it was supplied by the client.
        request = self.factory.get(
            "/",
            REMOTE_ADDR="10.0.0.1",
            HTTP_X_FORWARDED_FOR="1.2.3.4, 203.0.113.9",
        )
        self.assertEqual(self._remote_addr_seen_by_view(request), "203.0.113.9")

    @override_settings(TRUSTED_PROXY_DEPTH=1)
    def test_original_peer_address_is_preserved(self):
        request = self.factory.get(
            "/", REMOTE_ADDR="10.0.0.1", HTTP_X_FORWARDED_FOR="203.0.113.9"
        )
        XForwardedForMiddleware(lambda req: "response")(request)
        self.assertEqual(request.META["HTTP_X_PROXY_REMOTE_ADDR"], "10.0.0.1")

    @override_settings(TRUSTED_PROXY_DEPTH=2)
    def test_short_chain_is_not_trusted(self):
        # Fewer entries than trusted proxies means the header did not come
        # through our proxies as expected, so it is ignored.
        request = self.factory.get(
            "/", REMOTE_ADDR="10.0.0.1", HTTP_X_FORWARDED_FOR="1.2.3.4"
        )
        self.assertEqual(self._remote_addr_seen_by_view(request), "10.0.0.1")
