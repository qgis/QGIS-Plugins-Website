"""What must stay true after the rating feature was removed (issue #439).

Three separate concerns, none of which the other tests would catch:

* ``plugins.xml`` still carries ``<average_vote>`` and ``<rating_votes>``,
  pinned to 0. The feed is public and mirrored, and a consumer doing
  ``float(node.find("average_vote").text)`` raises AttributeError on a missing
  element but tolerates 0. This test exists to stop a well meaning future
  cleanup from quietly dropping them before QGIS Desktop has shipped its own
  rating removal.
* the retired URLs are gone and stale bookmarks carrying ``?sort=`` do not 500.
* every list view still renders. Removing the rating keys edited six separate
  ``.extra(select=...)`` blocks of raw SQL, and a typo in any one of them is a
  500 that no other test would reach.
"""

import tempfile
from xml.etree import ElementTree

from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.test import Client, TestCase, override_settings
from django.urls import NoReverseMatch, reverse
from plugins.models import Plugin, PluginVersion


class RatingRemovalTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        # plugins.xml resolves the set of trusted uploaders and indexes [0] into
        # it, so the feed needs at least one superuser or can_approve user to
        # render at all. Production always has one.
        User.objects.create_superuser(
            username="rating_admin", email="admin@example.com", password="password"
        )
        self.user = User.objects.create_user(
            username="rating_author", email="author@example.com", password="password"
        )
        self.plugin = Plugin.objects.create(
            package_name="rating_plugin",
            name="Rating Plugin",
            description="A test plugin",
            about="About text",
            author="Test Author",
            email="author@example.com",
            created_by=self.user,
            maintainer=self.user,
        )
        version = PluginVersion(
            plugin=self.plugin,
            version="1.0.0",
            min_qg_version="3.0.0",
            max_qg_version="3.99.0",
            experimental=False,
            approved=True,
            created_by=self.user,
        )
        version.package.save("rating_plugin.1.0.0.zip", ContentFile(b"PK"), save=False)
        version.save()


class XmlFeedVoteElementsTest(RatingRemovalTestCase):
    def test_feed_emits_constant_vote_elements(self):
        """Both elements present on every plugin, both exactly "0".

        Two things have to be arranged or this test silently checks nothing:

        * the feed defaults to qgis=1.8.0, which filters out a plugin declaring
          min_qg_version 3.0.0, so the version is asked for explicitly;
        * xml_plugins returns a pre-rendered file straight from
          MEDIA_ROOT/cached_xmls if one exists for the requested version,
          without touching the database or this template. MEDIA_ROOT is
          redirected at an empty directory so the template actually runs.
          (In production the beat task regenerates those files every ten
          minutes, so they pick the change up on their own.)
        """
        with tempfile.TemporaryDirectory() as empty_media_root:
            with override_settings(MEDIA_ROOT=empty_media_root):
                response = self.client.get("/plugins/plugins.xml", {"qgis": "3.10"})
        self.assertEqual(response.status_code, 200)

        root = ElementTree.fromstring(response.content)
        plugins = root.findall("pyqgis_plugin")
        self.assertGreater(len(plugins), 0, "feed rendered no plugins to assert on")

        for plugin in plugins:
            average_vote = plugin.find("average_vote")
            rating_votes = plugin.find("rating_votes")

            self.assertIsNotNone(
                average_vote, "average_vote must stay in the feed for old clients"
            )
            self.assertIsNotNone(
                rating_votes, "rating_votes must stay in the feed for old clients"
            )
            self.assertEqual(average_vote.text.strip(), "0")
            self.assertEqual(rating_votes.text.strip(), "0")

            # A multi-line note written with Django's short comment form is
            # emitted verbatim rather than stripped, which put explanatory prose
            # inside every entry of the public feed. ElementTree still parses
            # that happily, so the element assertions above do not catch it:
            # the stray text lands in pyqgis_plugin's own text node.
            self.assertEqual(
                (plugin.text or "").strip(),
                "",
                "stray text in <pyqgis_plugin> -- a template comment is leaking "
                "into the feed",
            )

    def test_template_comment_does_not_reach_the_feed(self):
        """The explanatory note in the template must never be rendered.

        Asserted on a phrase unique to the comment rather than on "{#" or
        "{%": plugin descriptions are arbitrary user text and a real one on
        plugins.qgis.org already contains "QGIS PSC", so generic markers would
        make this test fail on content it is not meant to police.
        """
        with tempfile.TemporaryDirectory() as empty_media_root:
            with override_settings(MEDIA_ROOT=empty_media_root):
                response = self.client.get("/plugins/plugins.xml", {"qgis": "3.10"})

        body = response.content.decode()
        self.assertNotIn("Drop the two elements only once", body)
        self.assertNotIn("endcomment", body)


class RetiredRatingUrlsTest(RatingRemovalTestCase):
    def test_most_voted_and_best_rated_are_gone(self):
        for name, path in [
            ("most_voted_plugins", "/plugins/most_voted/"),
            ("best_rated_plugins", "/plugins/best_rated/"),
        ]:
            with self.subTest(url=path):
                with self.assertRaises(NoReverseMatch):
                    reverse(name)
                self.assertEqual(self.client.get(path).status_code, 404)

    def test_plugin_rate_url_is_gone(self):
        with self.assertRaises(NoReverseMatch):
            reverse("plugin_rate", args=[self.plugin.pk, 5])
        response = self.client.post(f"/plugins/rate/{self.plugin.pk}/5/")
        self.assertEqual(response.status_code, 404)

    def test_stale_rating_sort_param_is_ignored(self):
        """An old bookmark or a cached crawler URL must not 500.

        The field fails the sort whitelist and then fails ``_is_valid_field``,
        so the ordering falls through to Plugin.Meta.ordering.
        """
        for sort in ["weighted_rating", "average_vote", "rating_votes"]:
            with self.subTest(sort=sort):
                response = self.client.get(
                    reverse("approved_plugins"), {"sort": sort, "order": "desc"}
                )
                self.assertEqual(response.status_code, 200)


class PluginListViewsRenderTest(RatingRemovalTestCase):
    """Smoke every list view: each one runs a hand written .extra() block."""

    def test_list_views_render(self):
        for name in [
            "approved_plugins",
            "popular_plugins",
            "most_downloaded_plugins",
            "stable_plugins",
            "experimental_plugins",
            "server_plugins",
            "deprecated_plugins",
            "fresh_plugins",
            "latest_plugins",
        ]:
            with self.subTest(view=name):
                response = self.client.get(reverse(name))
                self.assertEqual(response.status_code, 200)

    def test_authenticated_list_views_render(self):
        self.client.force_login(self.user)
        for name in ["unapproved_plugins", "my_plugins"]:
            with self.subTest(view=name):
                response = self.client.get(reverse(name))
                self.assertEqual(response.status_code, 200)


class PopularityOrderingTest(TestCase):
    """Popularity is downloads per day, so recency breaks a downloads tie."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="pop_author", email="pop@example.com", password="password"
        )

    def _approved_plugin(self, package_name, downloads, age_days):
        from datetime import timedelta

        from django.utils import timezone

        plugin = Plugin.objects.create(
            package_name=package_name,
            name=package_name,
            description="A test plugin",
            about="About text",
            author="Test Author",
            email="pop@example.com",
            created_by=self.user,
            maintainer=self.user,
            downloads=downloads,
        )
        # created_on is auto_now_add, so it has to be written back afterwards.
        Plugin.objects.filter(pk=plugin.pk).update(
            created_on=timezone.now() - timedelta(days=age_days)
        )
        version = PluginVersion(
            plugin=plugin,
            version="1.0.0",
            min_qg_version="3.0.0",
            max_qg_version="3.99.0",
            experimental=False,
            approved=True,
            created_by=self.user,
        )
        version.package.save(
            f"{package_name}.1.0.0.zip", ContentFile(b"PK"), save=False
        )
        version.save()
        return plugin

    def test_recent_plugin_outranks_older_one_with_equal_downloads(self):
        self._approved_plugin("slow_burner", downloads=1000, age_days=1000)
        self._approved_plugin("rising_star", downloads=1000, age_days=10)

        ordered = list(
            Plugin.popular_objects.filter(
                package_name__in=["slow_burner", "rising_star"]
            ).values_list("package_name", flat=True)
        )

        self.assertEqual(ordered[0], "rising_star")

    def test_brand_new_plugin_does_not_top_the_chart(self):
        """The GREATEST(..., 1) floor stops an hours-old plugin winning."""
        self._approved_plugin("established", downloads=10000, age_days=100)
        self._approved_plugin("just_uploaded", downloads=3, age_days=0)

        ordered = list(
            Plugin.popular_objects.filter(
                package_name__in=["established", "just_uploaded"]
            ).values_list("package_name", flat=True)
        )

        self.assertEqual(ordered[0], "established")
