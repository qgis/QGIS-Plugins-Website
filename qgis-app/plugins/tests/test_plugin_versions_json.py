"""
Tests for the plugin JSON endpoints (issue #227):
  - GET /plugins/<package_name>.json          -> all approved versions
  - GET /plugins/<package_name>/<version>.json -> specific version
  - GET /plugins/<package_name>/latest/        -> redirect to latest version detail
  - GET /plugins/<package_name>/?latest        -> same redirect via query param
"""

import json

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse
from plugins.models import Plugin, PluginVersion


def _make_plugin(creator, package_name="test_plugin", name="Test Plugin"):
    """Create a minimal Plugin owned by *creator*."""
    return Plugin.objects.create(
        package_name=package_name,
        name=name,
        description="A test plugin",
        about="About text",
        author="Test Author",
        email="author@example.com",
        created_by=creator,
        maintainer=creator,
    )


def _make_version(plugin, creator, version="1.0.0", experimental=False, approved=True):
    """Create a PluginVersion for *plugin*."""
    from django.core.files.base import ContentFile

    pv = PluginVersion(
        plugin=plugin,
        version=version,
        min_qg_version="3.0.0",
        max_qg_version="3.99.0",
        experimental=experimental,
        approved=approved,
        created_by=creator,
    )
    # PluginVersion requires a package file field; supply a dummy
    pv.package.save(
        f"{plugin.package_name}.{version}.zip",
        ContentFile(b"PK"),
        save=False,
    )
    pv.save()
    return pv


class PluginVersionsJsonEndpointTests(TestCase):
    fixtures = ["fixtures/auth.json"]

    def setUp(self):
        self.client = Client()
        self.creator = User.objects.get(username="creator")
        self.plugin = _make_plugin(self.creator)
        self.v1 = _make_version(self.plugin, self.creator, version="1.0.0")
        self.v2 = _make_version(
            self.plugin, self.creator, version="2.0.0", experimental=True
        )
        self.url = reverse("plugin_versions_json", args=["test_plugin"])

    def test_returns_200_for_approved_plugin(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/json")

    def test_returns_404_for_unknown_plugin(self):
        url = reverse("plugin_versions_json", args=["nonexistent_plugin"])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

    def test_returns_404_when_no_approved_versions(self):
        # Mark all versions unapproved
        self.plugin.pluginversion_set.update(approved=False)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 404)

    def test_response_structure(self):
        data = json.loads(self.client.get(self.url).content)

        # Top-level keys
        for key in (
            "name",
            "package_name",
            "description",
            "about",
            "homepage",
            "repository",
            "tracker",
            "author",
            "tags",
            "downloads",
            "latest_version",
            "versions",
        ):
            self.assertIn(key, data, msg=f"Missing top-level key: {key}")

        # Version entry keys
        self.assertTrue(len(data["versions"]) > 0)
        v = data["versions"][0]
        for key in (
            "version",
            "experimental",
            "qgis_min",
            "qgis_max",
            "downloads",
            "uploaded_by",
            "upload_datetime",
        ):
            self.assertIn(key, v, msg=f"Missing version key: {key}")

    def test_latest_version_is_highest(self):
        data = json.loads(self.client.get(self.url).content)
        self.assertEqual(data["latest_version"], "2.0.0")

    def test_only_approved_versions_returned(self):
        unapproved = _make_version(
            self.plugin, self.creator, version="3.0.0", approved=False
        )
        data = json.loads(self.client.get(self.url).content)
        versions_returned = [v["version"] for v in data["versions"]]
        self.assertNotIn("3.0.0", versions_returned)
        self.assertIn("1.0.0", versions_returned)
        self.assertIn("2.0.0", versions_returned)

    def test_correct_plugin_metadata(self):
        data = json.loads(self.client.get(self.url).content)
        self.assertEqual(data["name"], "Test Plugin")
        self.assertEqual(data["package_name"], "test_plugin")
        self.assertEqual(data["author"], "Test Author")

    def test_version_uploaded_by_is_username(self):
        data = json.loads(self.client.get(self.url).content)
        usernames = {v["uploaded_by"] for v in data["versions"]}
        self.assertIn(self.creator.username, usernames)

    def tearDown(self):
        # Clean up package files created during testing
        for pv in PluginVersion.objects.filter(plugin=self.plugin):
            if pv.package:
                try:
                    pv.package.delete(save=False)
                except Exception:
                    pass


class PluginVersionJsonEndpointTests(TestCase):
    fixtures = ["fixtures/auth.json"]

    def setUp(self):
        self.client = Client()
        self.creator = User.objects.get(username="creator")
        self.plugin = _make_plugin(
            self.creator, package_name="specific_plugin", name="Specific Plugin"
        )
        self.v1 = _make_version(self.plugin, self.creator, version="1.0.0")
        self.url = reverse("plugin_version_json", args=["specific_plugin", "1.0.0"])

    def test_returns_200_for_existing_approved_version(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/json")

    def test_returns_404_for_unknown_plugin(self):
        url = reverse("plugin_version_json", args=["nonexistent", "1.0.0"])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

    def test_returns_404_for_unapproved_version(self):
        unapproved = _make_version(
            self.plugin, self.creator, version="2.0.0", approved=False
        )
        url = reverse("plugin_version_json", args=["specific_plugin", "2.0.0"])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

    def test_returns_404_for_unknown_version(self):
        url = reverse("plugin_version_json", args=["specific_plugin", "9.9.9"])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

    def test_response_structure(self):
        data = json.loads(self.client.get(self.url).content)
        for key in (
            "name",
            "package_name",
            "version",
            "experimental",
            "qgis_min",
            "qgis_max",
            "downloads",
            "uploaded_by",
            "upload_datetime",
            "changelog",
            "external_deps",
            "download_url",
        ):
            self.assertIn(key, data, msg=f"Missing key: {key}")

    def test_correct_version_data(self):
        data = json.loads(self.client.get(self.url).content)
        self.assertEqual(data["version"], "1.0.0")
        self.assertEqual(data["package_name"], "specific_plugin")
        self.assertFalse(data["experimental"])
        self.assertEqual(data["qgis_min"], "3.0.0")
        self.assertIn("specific_plugin", data["download_url"])

    def tearDown(self):
        for pv in PluginVersion.objects.filter(plugin=self.plugin):
            if pv.package:
                try:
                    pv.package.delete(save=False)
                except Exception:
                    pass


class PluginLatestRedirectTests(TestCase):
    fixtures = ["fixtures/auth.json"]

    def setUp(self):
        self.client = Client()
        self.creator = User.objects.get(username="creator")
        self.plugin = _make_plugin(
            self.creator, package_name="redirect_plugin", name="Redirect Plugin"
        )
        self.v1 = _make_version(self.plugin, self.creator, version="1.0.0")
        self.v2 = _make_version(self.plugin, self.creator, version="2.0.0")
        self.latest_url = reverse("plugin_latest_redirect", args=["redirect_plugin"])

    def test_latest_redirect_returns_302(self):
        response = self.client.get(self.latest_url)
        self.assertEqual(response.status_code, 302)

    def test_latest_redirect_points_to_highest_version(self):
        response = self.client.get(self.latest_url)
        expected = reverse("version_detail", args=["redirect_plugin", "2.0.0"])
        self.assertIn("2.0.0", response["Location"])

    def test_latest_redirect_404_for_unknown_plugin(self):
        url = reverse("plugin_latest_redirect", args=["nonexistent_redirect"])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

    def test_latest_redirect_404_when_no_approved_versions(self):
        self.plugin.pluginversion_set.update(approved=False)
        response = self.client.get(self.latest_url)
        self.assertEqual(response.status_code, 404)

    def test_latest_json_redirect_returns_302(self):
        url = reverse("plugin_latest_json_redirect", args=["redirect_plugin"])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)

    def test_latest_json_redirect_points_to_version_json(self):
        url = reverse("plugin_latest_json_redirect", args=["redirect_plugin"])
        response = self.client.get(url)
        expected = reverse("plugin_version_json", args=["redirect_plugin", "2.0.0"])
        self.assertEqual(response["Location"], expected)

    def test_latest_json_redirect_404_for_unknown_plugin(self):
        url = reverse("plugin_latest_json_redirect", args=["nonexistent_redirect"])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

    def test_latest_json_redirect_404_when_no_approved_versions(self):
        self.plugin.pluginversion_set.update(approved=False)
        url = reverse("plugin_latest_json_redirect", args=["redirect_plugin"])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

    def tearDown(self):
        for pv in PluginVersion.objects.filter(plugin=self.plugin):
            if pv.package:
                try:
                    pv.package.delete(save=False)
                except Exception:
                    pass
