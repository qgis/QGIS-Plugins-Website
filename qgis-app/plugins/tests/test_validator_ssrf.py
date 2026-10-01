"""
Regression tests for the SSRF guard on the plugin upload url validator.

An authenticated plugin author supplies the tracker, repository and homepage
urls, and the server fetches them during validation. Without a guard that lets
the author aim the server at its own network. These tests stand up loopback
http listeners and drive plugins.validator._check_url_link against them, the
same shape as the reported proof of concept, and assert that:

  * an internal url is refused and never fetched
  * a redirect to an internal host is refused at the redirect hop
  * every kind of failure returns one identical message, so the error cannot
    be used to tell open from closed from filtered
  * a public, reachable url still passes, so ordinary uploads keep working

Everything binds to 127.0.0.1. No test makes a request off this machine.
"""

import http.server
import socket
import threading
from unittest import mock

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase
from plugins import safe_http
from plugins.validator import _check_url_link


def _free_port_on(host="127.0.0.1"):
    s = socket.socket()
    s.bind((host, 0))
    port = s.getsockname()[1]
    s.close()
    return port


class _Listener:
    """A throwaway loopback http server that records what it was asked for."""

    def __init__(self, redirect_to=None, host="127.0.0.1"):
        self.hits = []
        self.host = host
        self.port = _free_port_on(host)
        hits = self.hits

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _serve(self):
                hits.append((self.command, self.path))
                if redirect_to:
                    self.send_response(302)
                    self.send_header("Location", redirect_to)
                    self.end_headers()
                else:
                    self.send_response(200)
                    self.end_headers()

            do_HEAD = _serve
            do_GET = _serve

        self._srv = http.server.HTTPServer((host, self.port), Handler)

    def __enter__(self):
        threading.Thread(target=self._srv.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *exc):
        self._srv.shutdown()
        self._srv.server_close()


def _urls(url):
    return [
        {"url": url, "forbidden_url": "http://bugs", "metadata_attr": "tracker"},
        {"url": url, "forbidden_url": "http://repo", "metadata_attr": "repository"},
        {"url": url, "forbidden_url": "http://homepage", "metadata_attr": "homepage"},
    ]


class SsrfGuardTest(SimpleTestCase):
    def test_internal_url_is_refused_and_never_fetched(self):
        with _Listener() as internal:
            url = f"http://127.0.0.1:{internal.port}/probe"
            with self.assertRaises(ValidationError):
                _check_url_link(_urls(url))
            self.assertEqual(
                internal.hits, [], "the server must not reach an internal url"
            )

    def test_redirect_to_internal_host_is_refused_at_the_redirect_hop(self):
        """
        Isolates the redirect hop. The bait listens on 127.0.0.1 and the
        redirect target on 127.0.0.2, so the two hops have distinct addresses.
        The patched policy allows the bait address and blocks the target, which
        forces the guard to prove it validates the connection opened to follow
        the redirect, not only the url the author typed.
        """
        # Destination on a second loopback address, the whole 127.0.0.0/8 is
        # loopback, so 127.0.0.2 is reachable without any extra setup.
        with _Listener(host="127.0.0.2") as destination:
            target = f"http://127.0.0.2:{destination.port}/internal"
            with _Listener(redirect_to=target) as bait:
                bait_url = f"http://127.0.0.1:{bait.port}/b"

                # Baseline: with nothing blocked the redirect is followed, so
                # the destination is reached. This proves the test would notice
                # an unguarded redirect.
                with mock.patch.object(
                    safe_http, "is_blocked_address", return_value=False
                ):
                    try:
                        _check_url_link(_urls(bait_url))
                    except ValidationError:
                        pass
                self.assertTrue(
                    destination.hits,
                    "baseline: the redirect destination is reached when unguarded",
                )

                destination.hits.clear()
                bait.hits.clear()

                # Allow the bait address, block the redirect target.
                def policy(host):
                    return host == "127.0.0.2"

                with mock.patch.object(
                    safe_http, "is_blocked_address", side_effect=policy
                ):
                    with self.assertRaises(ValidationError):
                        _check_url_link(_urls(bait_url))

                self.assertTrue(
                    bait.hits, "the allowed first hop should still be reached"
                )
                self.assertEqual(
                    destination.hits,
                    [],
                    "the blocked redirect target must never be reached",
                )

    def test_failure_message_is_identical_for_every_cause(self):
        messages = []

        # blocked internal host
        with _Listener() as internal:
            try:
                _check_url_link(_urls(f"http://127.0.0.1:{internal.port}/x"))
            except ValidationError as e:
                messages.append(str(e.messages[0]))

        # closed port, nothing listening
        closed = _free_port_on()
        try:
            _check_url_link(_urls(f"http://127.0.0.1:{closed}/x"))
        except ValidationError as e:
            messages.append(str(e.messages[0]))

        self.assertEqual(
            messages[0],
            messages[1],
            "blocked and closed must be indistinguishable to the uploader",
        )
        leaky = ("ConnectionError", "HTTP status", "timeout", str(closed))
        for token in leaky:
            self.assertNotIn(
                token,
                messages[0],
                f"the message must not disclose {token!r}",
            )

    def test_public_reachable_url_still_passes(self):
        """A legitimate link must still validate, so uploads are not broken."""
        with _Listener() as public:
            url = f"http://127.0.0.1:{public.port}/ok"
            with mock.patch.object(safe_http, "is_blocked_address", return_value=False):
                # No exception means the link validated.
                _check_url_link(_urls(url))
            self.assertTrue(public.hits, "a reachable url is actually fetched")


class IsBlockedAddressTest(SimpleTestCase):
    def test_blocks_internal_ranges(self):
        for addr in (
            "127.0.0.1",
            "10.1.2.3",
            "172.16.9.9",
            "192.168.0.5",
            "169.254.169.254",
            "::1",
            "fe80::1",
            "fc00::1",
            "0.0.0.0",
        ):
            self.assertTrue(
                safe_http.is_blocked_address(addr), f"{addr} should be blocked"
            )

    def test_allows_public_addresses(self):
        for addr in ("8.8.8.8", "1.1.1.1", "93.184.216.34", "2606:4700:4700::1111"):
            self.assertFalse(
                safe_http.is_blocked_address(addr), f"{addr} should be allowed"
            )

    def test_blocks_scoped_ipv6_and_garbage(self):
        self.assertTrue(safe_http.is_blocked_address("fe80::1%eth0"))
        self.assertTrue(safe_http.is_blocked_address("not-an-ip"))
