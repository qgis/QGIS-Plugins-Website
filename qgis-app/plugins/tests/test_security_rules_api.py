"""
Unit tests for the public read-only security-rules API.

    GET /plugins/api/security-rules/

This endpoint is the single source of rule truth for the standalone
security-check CLI, so it must expose exactly the enabled rules plus the
platform's analysis-tool versions.
"""
import json

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from plugins.models import SecurityRule


class SecurityRulesApiTest(TestCase):
    def setUp(self):
        # The endpoint is cache_page-decorated; LocMemCache is not rolled back
        # between test methods, so clear it to avoid cross-test pollution.
        cache.clear()
        SecurityRule.objects.create(
            check_category="bandit",
            check_code="B602",
            check_name="subprocess with shell=True",
            check_description="Shell injection risk.",
            severity="critical",
            enabled=True,
            can_be_skipped=False,
        )
        SecurityRule.objects.create(
            check_category="flake8",
            check_code="E501",
            check_name="Line too long",
            check_description="Style issue.",
            severity="warning",
            enabled=True,
            can_be_skipped=True,
        )
        # A disabled rule must NOT be exposed in the "rules" list.
        SecurityRule.objects.create(
            check_category="flake8",
            check_code="W503",
            check_name="Line break before binary operator",
            check_description="Style preference.",
            severity="info",
            enabled=False,
            can_be_skipped=True,
        )
        # A secrets rule (disabled) must still appear in secrets_plugins.
        SecurityRule.objects.create(
            check_category="secrets",
            check_code="KeywordDetector",
            check_name="Keyword detector",
            check_description="Finds password-like keywords.",
            severity="critical",
            enabled=False,
            can_be_skipped=False,
        )

    def _get(self):
        resp = self.client.get(reverse("security_rules_api"))
        self.assertEqual(resp.status_code, 200)
        return json.loads(resp.content)

    def test_returns_only_enabled_rules(self):
        data = self._get()
        codes = {r["check_code"] for r in data["rules"]}
        self.assertIn("B602", codes)
        self.assertIn("E501", codes)
        self.assertNotIn("W503", codes)  # disabled

    def test_rule_shape(self):
        data = self._get()
        rule = next(r for r in data["rules"] if r["check_code"] == "B602")
        for field in (
            "check_code",
            "check_category",
            "check_name",
            "severity",
            "enabled",
            "can_be_skipped",
        ):
            self.assertIn(field, rule)
        self.assertTrue(rule["enabled"])
        self.assertFalse(rule["can_be_skipped"])

    def test_secrets_plugins_includes_disabled_secrets_rule(self):
        data = self._get()
        self.assertIn("KeywordDetector", data["secrets_plugins"])

    def test_tool_versions_present(self):
        data = self._get()
        self.assertIn("tool_versions", data)
        for dist in ("bandit", "detect-secrets", "flake8"):
            self.assertIn(dist, data["tool_versions"])

    def test_endpoint_is_public(self):
        # No authentication and no plugin record required.
        resp = self.client.get(reverse("security_rules_api"))
        self.assertEqual(resp.status_code, 200)

    def test_only_get_allowed(self):
        resp = self.client.post(reverse("security_rules_api"))
        self.assertEqual(resp.status_code, 405)
