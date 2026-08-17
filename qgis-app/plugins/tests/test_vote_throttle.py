from datetime import timedelta

from django.contrib.auth.models import AnonymousUser, User
from django.core.exceptions import ValidationError
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from djangoratings.exceptions import IPLimitReached
from freezegun import freeze_time
from middleware import XForwardedForMiddleware
from plugins.api import plugin_vote
from plugins.models import Plugin
from plugins.vote_throttle import anonymous_vote_cookies, vote_cookie_name


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


class AnonymousVoteThrottleTest(TestCase):
    """Anonymous votes from one address on one plugin collapse into one vote."""

    fixtures = ["fixtures/auth.json"]

    def setUp(self):
        self.creator = User.objects.get(id=2)
        self.plugin = Plugin.objects.create(
            created_by=self.creator,
            repository="http://example.com",
            tracker="http://example.com",
            package_name="test-vote-throttle",
            name="test vote throttle",
            about="this is a test for anonymous vote throttling",
        )
        self.url = reverse("plugin_rate", args=[self.plugin.pk, 5])

    def _rate(self, score, remote_addr="203.0.113.9"):
        """POST a vote as an anonymous client that keeps no cookies."""
        self.client.cookies.clear()
        return self.client.post(
            reverse("plugin_rate", args=[self.plugin.pk, score]),
            REMOTE_ADDR=remote_addr,
        )

    def _reload(self):
        return Plugin.objects.get(pk=self.plugin.pk)

    def test_single_vote_is_recorded(self):
        self._rate(5)
        plugin = self._reload()
        self.assertEqual(plugin.rating_votes, 1)
        self.assertEqual(plugin.rating_score, 5)

    def test_repeated_votes_from_same_address_count_once(self):
        for _ in range(10):
            self._rate(1)

        plugin = self._reload()
        self.assertEqual(plugin.rating_votes, 1)
        self.assertEqual(plugin.rating_score, 1)

    def test_repeated_votes_with_forged_cookies_count_once(self):
        # A client that invents a new vote cookie on every request used to look
        # like a new voter each time and slip past the throttle entirely.
        cookie_name = vote_cookie_name(self.plugin)
        url = reverse("plugin_rate", args=[self.plugin.pk, 1])
        for attempt in range(10):
            self.client.cookies.clear()
            self.client.cookies[cookie_name] = "forged-%d" % attempt
            self.client.post(url, REMOTE_ADDR="203.0.113.9")

        plugin = self._reload()
        self.assertEqual(plugin.rating_votes, 1)
        self.assertEqual(plugin.rating_score, 1)

    def test_repeated_votes_replace_rather_than_accumulate(self):
        self._rate(5)
        self._rate(1)

        plugin = self._reload()
        self.assertEqual(plugin.rating_votes, 1)
        self.assertEqual(plugin.rating_score, 1)

    def test_different_addresses_vote_independently(self):
        self._rate(5, remote_addr="203.0.113.9")
        self._rate(1, remote_addr="198.51.100.7")

        plugin = self._reload()
        self.assertEqual(plugin.rating_votes, 2)
        self.assertEqual(plugin.rating_score, 6)

    def test_vote_after_window_expires_is_a_new_vote(self):
        with freeze_time("2026-01-01 12:00:00"):
            self._rate(5)
        with freeze_time("2026-01-20 12:00:00"):
            self._rate(1)

        plugin = self._reload()
        self.assertEqual(plugin.rating_votes, 2)
        self.assertEqual(plugin.rating_score, 6)

    def test_unknown_plugin_returns_404(self):
        response = self.client.post(reverse("plugin_rate", args=[999999, 5]))
        self.assertEqual(response.status_code, 404)

    def test_get_is_rejected(self):
        response = self.client.get(reverse("plugin_rate", args=[self.plugin.pk, 5]))
        self.assertEqual(response.status_code, 405)


class AnonymousVoteCookiesTest(TestCase):
    """Unit level checks on the cookie replacement helper."""

    fixtures = ["fixtures/auth.json"]

    def setUp(self):
        self.factory = RequestFactory()
        self.creator = User.objects.get(id=2)
        self.plugin = Plugin.objects.create(
            created_by=self.creator,
            repository="http://example.com",
            tracker="http://example.com",
            package_name="test-vote-cookies",
            name="test vote cookies",
            about="this is a test for the vote cookie helper",
        )

    def _request(self, remote_addr="203.0.113.9", user=None, cookies=None):
        request = self.factory.post("/", REMOTE_ADDR=remote_addr)
        request.user = user or AnonymousUser()
        request.COOKIES = cookies or {}
        return request

    def test_authenticated_users_are_not_throttled(self):
        self.plugin.rating.add(
            score=5, user=self.creator, ip_address="203.0.113.9", cookies={}
        )
        request = self._request(user=self.creator)
        self.assertEqual(anonymous_vote_cookies(request, self.plugin), {})

    def test_cookie_naming_a_real_vote_is_left_alone(self):
        self.plugin.rating.add(
            score=5, user=None, ip_address="198.51.100.7", cookies={}
        )
        vote = self.plugin.rating.get_ratings().get()

        cookie_name = vote_cookie_name(self.plugin)
        request = self._request(cookies={cookie_name: vote.cookie})
        self.assertEqual(
            anonymous_vote_cookies(request, self.plugin)[cookie_name],
            vote.cookie,
        )

    def test_cookie_naming_no_vote_is_discarded(self):
        # The client chooses what it sends, so a value we have no vote for is
        # worthless as evidence and must not stand in for one.
        cookie_name = vote_cookie_name(self.plugin)
        request = self._request(cookies={cookie_name: "made-up"})
        self.assertEqual(anonymous_vote_cookies(request, self.plugin), {})

    def test_forged_cookie_does_not_suppress_the_address_lookup(self):
        self.plugin.rating.add(score=5, user=None, ip_address="203.0.113.9", cookies={})
        vote = self.plugin.rating.get_ratings().get()

        cookie_name = vote_cookie_name(self.plugin)
        request = self._request(
            remote_addr="203.0.113.9", cookies={cookie_name: "made-up"}
        )
        self.assertEqual(
            anonymous_vote_cookies(request, self.plugin)[cookie_name],
            vote.cookie,
        )

    def test_cookie_for_another_plugin_is_not_borrowed(self):
        other = Plugin.objects.create(
            created_by=self.creator,
            repository="http://example.com",
            tracker="http://example.com",
            package_name="test-vote-cookies-other",
            name="test vote cookies other",
            about="a second plugin whose vote cookie must not be reused",
        )
        other.rating.add(score=5, user=None, ip_address="198.51.100.7", cookies={})
        other_vote = other.rating.get_ratings().get()

        cookie_name = vote_cookie_name(self.plugin)
        request = self._request(cookies={cookie_name: other_vote.cookie})
        self.assertEqual(anonymous_vote_cookies(request, self.plugin), {})

    def test_unrelated_cookies_are_preserved(self):
        cookie_name = vote_cookie_name(self.plugin)
        request = self._request(cookies={cookie_name: "made-up", "sessionid": "abc"})
        self.assertEqual(
            anonymous_vote_cookies(request, self.plugin), {"sessionid": "abc"}
        )

    def test_recent_vote_cookie_is_replayed(self):
        self.plugin.rating.add(score=5, user=None, ip_address="203.0.113.9", cookies={})
        vote = self.plugin.rating.get_ratings().get()

        request = self._request(remote_addr="203.0.113.9")
        cookies = anonymous_vote_cookies(request, self.plugin)
        self.assertEqual(cookies[vote_cookie_name(self.plugin)], vote.cookie)

    def test_vote_from_another_address_is_not_replayed(self):
        self.plugin.rating.add(score=5, user=None, ip_address="203.0.113.9", cookies={})

        request = self._request(remote_addr="198.51.100.7")
        self.assertEqual(anonymous_vote_cookies(request, self.plugin), {})

    @override_settings(ANONYMOUS_VOTE_WINDOW_DAYS=1)
    def test_window_length_is_configurable(self):
        self.plugin.rating.add(score=5, user=None, ip_address="203.0.113.9", cookies={})
        # date_changed is auto_now, so bypass save() to age the vote.
        self.plugin.rating.get_ratings().update(
            date_changed=timezone.now() - timedelta(days=2)
        )

        request = self._request(remote_addr="203.0.113.9")
        self.assertEqual(anonymous_vote_cookies(request, self.plugin), {})

    def test_missing_remote_addr_is_left_to_the_caller(self):
        # Nothing to match on, so the helper passes the cookies through
        # unchanged rather than guessing.
        self.plugin.rating.add(score=5, user=None, ip_address="203.0.113.9", cookies={})

        request = self._request(remote_addr="")
        self.assertEqual(anonymous_vote_cookies(request, self.plugin), {})


@override_settings(RATINGS_VOTES_PER_IP=2, ANONYMOUS_VOTE_WINDOW_DAYS=1)
class VotesPerAddressCapTest(TestCase):
    """djangoratings caps votes per plugin per address, independently of us."""

    fixtures = ["fixtures/auth.json"]

    def setUp(self):
        self.creator = User.objects.get(id=2)
        self.plugin = Plugin.objects.create(
            created_by=self.creator,
            repository="http://example.com",
            tracker="http://example.com",
            package_name="test-vote-ip-cap",
            name="test vote ip cap",
            about="this is a test for the per address vote cap",
        )

    def _vote_beyond_the_window(self, score, ip_address="203.0.113.9"):
        """Record a vote, then age it so the throttle will not replay it.

        This isolates the cap: every call is a fresh vote as far as
        plugins.vote_throttle is concerned, which is the situation the cap
        exists to catch.
        """
        self.plugin.rating.add(
            score=score, user=None, ip_address=ip_address, cookies={}
        )
        # date_changed is auto_now, so bypass save() to age the votes.
        self.plugin.rating.get_ratings().update(
            date_changed=timezone.now() - timedelta(days=2)
        )

    def test_votes_up_to_the_cap_are_recorded(self):
        self._vote_beyond_the_window(5)
        self._vote_beyond_the_window(5)

        self.assertEqual(self.plugin.rating.get_ratings().count(), 2)

    def test_vote_past_the_cap_is_refused(self):
        self._vote_beyond_the_window(5)
        self._vote_beyond_the_window(5)

        with self.assertRaises(IPLimitReached):
            self._vote_beyond_the_window(5)

        self.assertEqual(self.plugin.rating.get_ratings().count(), 2)

    def test_cap_is_per_address(self):
        self._vote_beyond_the_window(5)
        self._vote_beyond_the_window(5)
        self._vote_beyond_the_window(5, ip_address="198.51.100.7")

        self.assertEqual(self.plugin.rating.get_ratings().count(), 3)

    def test_rpc_reports_the_cap_as_a_validation_error(self):
        self._vote_beyond_the_window(5)
        self._vote_beyond_the_window(5)

        request = RequestFactory().post("/", REMOTE_ADDR="203.0.113.9")
        request.user = AnonymousUser()
        request.COOKIES = {}

        # The plugin manager should be told why, not handed an XML-RPC fault.
        with self.assertRaises(ValidationError):
            plugin_vote(self.plugin.pk, 5, request=request)
