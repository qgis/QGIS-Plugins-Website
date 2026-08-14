"""
Regression tests for SQL injection in the plugin XML feeds.

``/plugins/plugins_new.xml`` built its query by string formatting, so a quote in
the client supplied ``qgis`` parameter escaped the string literal it was meant
to sit in and ran as SQL. Observed before the fix: ``3.1' OR 1=1--`` returned
every row, ``3.1' AND 1=2--`` returned none, and ``3.1' UNION SELECT NULL--``
raised ProgrammingError from PostgreSQL.

There are two independent defences and they are tested separately:

* the queries pass the version bounds as parameters, so a quote is data. Those
  tests patch the sanitiser out, because parameterisation is what has to hold
  even if a raw value reaches the query.
* ``_clean_qgis_version`` strips the value to digits and dots on the way in.

The boolean-oracle pair (``AND 1=1`` versus ``AND 1=2``) is the sharp test: if
the payload were ever interpreted as SQL again the two responses would diverge,
whatever the rest of the feed contains.
"""

import os
import tempfile
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.test import Client, TestCase, override_settings
from plugins.models import Plugin, PluginVersion
from plugins.utils import QGIS_VERSION_LABELS
from plugins.views import _clean_qgis_version

# Payloads that reached the database before the fix.
INJECTION_PAYLOADS = [
    "3.1' OR 1=1--",
    "3.1' AND 1=2--",
    "3.1' UNION SELECT NULL--",
    "3.1' AND (SELECT COUNT(*) FROM auth_user WHERE is_superuser)>0--",
    "3.1'; DROP TABLE plugins_plugin;--",
]

# Differ only in a condition SQL would evaluate and a string comparison
# would not.
ORACLE_TRUE = "3.1' AND 1=1--"
ORACLE_FALSE = "3.1' AND 1=2--"


def _unsanitised(value):
    """Identity stand-in for ``_clean_qgis_version``.

    Lets a test drive a raw payload all the way to the query, so it exercises
    parameterisation rather than the input filter in front of it.
    """
    return value


class XmlFeedInjectionTest(TestCase):
    """The ``qgis`` parameter must never reach the database as SQL."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username="feed_author", email="author@example.com", password="password"
        )
        self.plugin = Plugin.objects.create(
            package_name="feed_plugin",
            name="Feed Plugin",
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
        version.package.save("feed_plugin.1.0.0.zip", ContentFile(b"PK"), save=False)
        version.save()

    @patch("plugins.views._clean_qgis_version", _unsanitised)
    def test_boolean_oracle_gives_no_signal(self):
        """A true and a false SQL condition must produce identical responses."""
        true_response = self.client.get(
            "/plugins/plugins_new.xml", {"qgis": ORACLE_TRUE}
        )
        false_response = self.client.get(
            "/plugins/plugins_new.xml", {"qgis": ORACLE_FALSE}
        )

        self.assertEqual(true_response.status_code, 200)
        self.assertEqual(false_response.status_code, 200)
        self.assertEqual(true_response.content, false_response.content)

    @patch("plugins.views._clean_qgis_version", _unsanitised)
    def test_payloads_are_treated_as_version_strings(self):
        """No payload errors, and none of them widens the result set."""
        baseline = self.client.get("/plugins/plugins_new.xml", {"qgis": "3.1"})
        self.assertEqual(baseline.status_code, 200)
        baseline_count = baseline.content.count(b"<pyqgis_plugin ")

        for payload in INJECTION_PAYLOADS:
            with self.subTest(payload=payload):
                response = self.client.get(
                    "/plugins/plugins_new.xml", {"qgis": payload}
                )
                # A ProgrammingError would surface as a 500 here.
                self.assertEqual(response.status_code, 200)
                self.assertLessEqual(
                    response.content.count(b"<pyqgis_plugin "), baseline_count
                )

    @patch("plugins.views._clean_qgis_version", _unsanitised)
    def test_experimental_pass_is_also_parameterised(self):
        """``stable_only=0`` runs the query a second time; it takes params too."""
        response = self.client.get(
            "/plugins/plugins_new.xml",
            {"qgis": ORACLE_TRUE, "stable_only": "0"},
        )
        self.assertEqual(response.status_code, 200)

    @patch("plugins.views._clean_qgis_version", _unsanitised)
    def test_table_survives_a_drop_attempt(self):
        """A statement terminator in the parameter must not run a second query."""
        self.client.get(
            "/plugins/plugins_new.xml",
            {"qgis": "3.1'; DROP TABLE plugins_plugin;--"},
        )
        self.assertTrue(Plugin.objects.filter(pk=self.plugin.pk).exists())

    def test_ordinary_versions_still_select_plugins(self):
        """Guard against the fix silently emptying the feed for real clients."""
        response = self.client.get("/plugins/plugins_new.xml", {"qgis": "3.34"})
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"feed_plugin", response.content)


class CachedXmlFeedTest(TestCase):
    """``xml_plugins`` builds a filename from the same parameter."""

    def setUp(self):
        self.client = Client()
        # xml_plugins reads the trusted-user list with list(zip(*qs))[0], which
        # raises IndexError on a site with no approvers and no superusers. That
        # cannot happen in production but does on an empty test database, so
        # the fixture mirrors production rather than working around it here.
        User.objects.create_superuser(
            username="feed_admin", email="admin@example.com", password="password"
        )

    def test_payloads_do_not_escape_the_cache_directory(self):
        """The version reaches a path; no payload may read outside MEDIA_ROOT."""
        with tempfile.TemporaryDirectory() as media_root:
            with override_settings(MEDIA_ROOT=media_root):
                for payload in INJECTION_PAYLOADS + ["../../../../etc/passwd"]:
                    with self.subTest(payload=payload):
                        response = self.client.get(
                            "/plugins/plugins.xml", {"qgis": payload}
                        )
                        self.assertEqual(response.status_code, 200)
                        self.assertNotIn(b"root:x:", response.content)

    def test_cached_label_feeds_are_still_served(self):
        """?qgis=ltr must keep hitting plugins_ltr.xml, not fall through.

        The three release channel labels are written by generate_plugins_xml
        and are the values QGIS itself sends for a channel rather than a
        pinned version.
        """
        with tempfile.TemporaryDirectory() as media_root:
            cache_dir = os.path.join(media_root, "cached_xmls")
            os.makedirs(cache_dir)
            for label in QGIS_VERSION_LABELS:
                with open(os.path.join(cache_dir, f"plugins_{label}.xml"), "w") as fh:
                    fh.write(f"<plugins>{label} cached feed</plugins>")

            with override_settings(MEDIA_ROOT=media_root):
                for label in list(QGIS_VERSION_LABELS) + ["LTR"]:
                    with self.subTest(label=label):
                        response = self.client.get(
                            "/plugins/plugins.xml", {"qgis": label}
                        )
                        self.assertEqual(response.status_code, 200)
                        self.assertIn(
                            f"{label.lower()} cached feed".encode(), response.content
                        )


class CleanQgisVersionTest(TestCase):
    """The sanitiser keeps real versions intact and drops everything else."""

    def test_real_versions_are_unchanged(self):
        for version in ["3", "3.34", "3.34.5", "1.8.0"]:
            with self.subTest(version=version):
                self.assertEqual(_clean_qgis_version(version), version)

    def test_quotes_and_keywords_are_stripped(self):
        self.assertEqual(_clean_qgis_version("3.1' OR 1=1--"), "3.111")
        self.assertEqual(_clean_qgis_version("3.1'; DROP TABLE x;--"), "3.1")

    def test_path_separators_are_stripped(self):
        """Slashes go too, so the value cannot walk out of a directory."""
        self.assertEqual(_clean_qgis_version("../../../etc/passwd"), "......")

    def test_empty_values_pass_through(self):
        self.assertEqual(_clean_qgis_version(""), "")
        self.assertIsNone(_clean_qgis_version(None))

    def test_release_channel_labels_survive(self):
        """generate_plugins_xml caches plugins_<label>.xml for these three.

        Stripping the letters would turn the label into an empty string, the
        cached feed would never be found, and every labelled request would fall
        through to a full database query.
        """
        for label in QGIS_VERSION_LABELS:
            with self.subTest(label=label):
                self.assertEqual(_clean_qgis_version(label), label)

    def test_labels_are_matched_case_insensitively_and_normalised(self):
        self.assertEqual(_clean_qgis_version("LTR"), "ltr")

    def test_words_outside_the_allow_list_are_still_stripped(self):
        """The allow list is exactly three literals, not "any word"."""
        self.assertEqual(_clean_qgis_version("ltr' OR 1=1--"), "11")
        self.assertEqual(_clean_qgis_version("nightly"), "")
