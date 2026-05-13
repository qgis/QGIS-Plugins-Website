"""
Tests for the plugin JSON endpoints (issue #227):
  - GET /plugins/<package_name>/json           -> all approved versions
  - GET /plugins/<package_name>/version/<v>/json -> specific version
  - GET /plugins/<package_name>/latest/        -> redirect to latest version detail
  - GET /plugins/<package_name>/latest/json    -> redirect to latest version JSON
  - GET /plugins/<package_name>/?latest        -> same redirect via query param
  - Bearer token / session auth -> extra fields (validation_status, security_scan)
"""

import json

from django.contrib.auth.models import User
from django.test import Client, RequestFactory, TestCase
from django.urls import reverse
from plugins.decorators import validate_plugin_token
from plugins.models import Plugin, PluginOutstandingToken, PluginVersion
from rest_framework_simplejwt.token_blacklist.models import (
    BlacklistedToken,
    OutstandingToken,
)
from rest_framework_simplejwt.tokens import RefreshToken


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


# ---------------------------------------------------------------------------
# Helpers shared by the auth-related test classes
# ---------------------------------------------------------------------------


def _make_plugin_token(user, plugin):
    """
    Create a PluginOutstandingToken for *plugin* and return
    ``(access_token_str, outstanding_token)``.
    Mirrors the logic in ``plugin_token_create``.
    """
    refresh = RefreshToken.for_user(user)
    refresh["plugin_id"] = plugin.pk
    refresh["refresh_jti"] = refresh["jti"]
    outstanding = OutstandingToken.objects.get(jti=refresh["jti"])
    PluginOutstandingToken.objects.create(
        plugin=plugin,
        token=outstanding,
        is_blacklisted=False,
        is_newly_created=False,
    )
    return str(refresh.access_token), outstanding


# ---------------------------------------------------------------------------
# validate_plugin_token unit tests
# ---------------------------------------------------------------------------


class ValidatePluginTokenTests(TestCase):
    fixtures = ["fixtures/auth.json"]

    def setUp(self):
        self.factory = RequestFactory()
        self.creator = User.objects.get(username="creator")
        self.plugin = _make_plugin(self.creator, package_name="token_test_plugin")
        self.access_token, self.outstanding = _make_plugin_token(
            self.creator, self.plugin
        )

    def _req(self, auth_header=None):
        request = self.factory.get("/")
        if auth_header:
            request.META["HTTP_AUTHORIZATION"] = auth_header
        return request

    def test_returns_false_without_auth_header(self):
        self.assertFalse(validate_plugin_token(self._req(), self.plugin))

    def test_returns_false_with_non_bearer_header(self):
        self.assertFalse(
            validate_plugin_token(self._req("Token sometoken"), self.plugin)
        )

    def test_returns_false_with_invalid_token(self):
        self.assertFalse(
            validate_plugin_token(self._req("Bearer not.a.valid.jwt"), self.plugin)
        )

    def test_returns_true_with_valid_token(self):
        request = self._req(f"Bearer {self.access_token}")
        self.assertTrue(validate_plugin_token(request, self.plugin))

    def test_sets_plugin_token_on_success(self):
        request = self._req(f"Bearer {self.access_token}")
        validate_plugin_token(request, self.plugin)
        self.assertIsNotNone(getattr(request, "plugin_token", None))
        self.assertEqual(request.plugin_token.plugin, self.plugin)

    def test_returns_false_for_wrong_plugin(self):
        other_plugin = _make_plugin(
            self.creator, package_name="other_token_plugin", name="Other Plugin"
        )
        request = self._req(f"Bearer {self.access_token}")
        # token was issued for self.plugin, not other_plugin
        self.assertFalse(validate_plugin_token(request, other_plugin))

    def test_returns_false_with_blacklisted_token(self):
        BlacklistedToken.objects.create(token=self.outstanding)
        request = self._req(f"Bearer {self.access_token}")
        self.assertFalse(validate_plugin_token(request, self.plugin))

    def tearDown(self):
        for pv in PluginVersion.objects.filter(
            plugin__package_name__startswith="token_test"
        ):
            if pv.package:
                try:
                    pv.package.delete(save=False)
                except Exception:
                    pass


# ---------------------------------------------------------------------------
# Authorized extra fields in the JSON endpoints
# ---------------------------------------------------------------------------


class AuthorizedJsonExtraFieldsTests(TestCase):
    """
    Authorized callers (session-authenticated editor or valid Bearer token)
    receive ``validation_status`` and ``security_scan`` in the JSON responses.
    Anonymous callers must not see those fields.
    """

    fixtures = ["fixtures/auth.json"]

    def setUp(self):
        self.creator = User.objects.get(username="creator")
        self.plugin = _make_plugin(
            self.creator, package_name="auth_fields_plugin", name="Auth Fields Plugin"
        )
        self.version = _make_version(self.plugin, self.creator, version="1.0.0")
        self.access_token, _ = _make_plugin_token(self.creator, self.plugin)
        self.versions_url = reverse("plugin_versions_json", args=["auth_fields_plugin"])
        self.version_url = reverse(
            "plugin_version_json", args=["auth_fields_plugin", "1.0.0"]
        )

    # -- /json (all versions) ------------------------------------------------

    def test_no_extra_fields_without_auth(self):
        data = self.client.get(self.versions_url).json()
        v = data["versions"][0]
        self.assertNotIn("validation_status", v)
        self.assertNotIn("security_scan", v)

    def test_extra_fields_with_session_auth(self):
        self.client.force_login(self.creator)
        data = self.client.get(self.versions_url).json()
        v = data["versions"][0]
        self.assertIn("validation_status", v)
        self.assertIn("security_scan", v)

    def test_extra_fields_with_bearer_token(self):
        client = Client(HTTP_AUTHORIZATION=f"Bearer {self.access_token}")
        data = client.get(self.versions_url).json()
        v = data["versions"][0]
        self.assertIn("validation_status", v)
        self.assertIn("security_scan", v)

    def test_no_extra_fields_with_invalid_bearer_token(self):
        client = Client(HTTP_AUTHORIZATION="Bearer invalid.token.here")
        data = client.get(self.versions_url).json()
        v = data["versions"][0]
        self.assertNotIn("validation_status", v)
        self.assertNotIn("security_scan", v)

    # -- /version/<version>/json ----------------------------------------------

    def test_version_no_extra_fields_without_auth(self):
        data = self.client.get(self.version_url).json()
        self.assertNotIn("validation_status", data)
        self.assertNotIn("security_scan", data)

    def test_version_extra_fields_with_session_auth(self):
        self.client.force_login(self.creator)
        data = self.client.get(self.version_url).json()
        self.assertIn("validation_status", data)
        self.assertIn("security_scan", data)

    def test_version_extra_fields_with_bearer_token(self):
        client = Client(HTTP_AUTHORIZATION=f"Bearer {self.access_token}")
        data = client.get(self.version_url).json()
        self.assertIn("validation_status", data)
        self.assertIn("security_scan", data)

    def test_version_security_scan_is_null_when_no_scan(self):
        """When no scan has run yet the field should be present but null."""
        self.client.force_login(self.creator)
        data = self.client.get(self.version_url).json()
        self.assertIsNone(data["security_scan"])

    def tearDown(self):
        for pv in PluginVersion.objects.filter(plugin=self.plugin):
            if pv.package:
                try:
                    pv.package.delete(save=False)
                except Exception:
                    pass
