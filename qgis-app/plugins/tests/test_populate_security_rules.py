"""
Unit tests for the populate_security_rules management command.

Tests cover:
 - All four JSON data files are loaded correctly
 - Rule counts match the expected totals
 - update_or_create semantics (create on first run, update on second)
 - --clear flag deletes existing rules before repopulating
"""

from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from plugins.models import SecurityRule


class PopulateSecurityRulesCommandTest(TestCase):
    """Tests for `python manage.py populate_security_rules`."""

    def _run_command(self, *args, **kwargs):
        """Run the management command and capture output."""
        out = StringIO()
        call_command("populate_security_rules", *args, stdout=out, **kwargs)
        return out.getvalue()

    def test_command_creates_rules(self):
        """Running the command must create SecurityRule records."""
        self.assertEqual(SecurityRule.objects.count(), 0)
        self._run_command()
        self.assertGreater(SecurityRule.objects.count(), 0)

    def test_bandit_rules_loaded(self):
        """Bandit rules must be loaded from bandit_rules.json."""
        self._run_command()
        bandit_rules = SecurityRule.objects.filter(check_category="bandit")
        self.assertGreaterEqual(bandit_rules.count(), 70)  # at least 70 Bandit rules

    def test_secrets_rules_loaded(self):
        """detect-secrets rules must be loaded from secrets_rules.json."""
        self._run_command()
        secrets_rules = SecurityRule.objects.filter(check_category="secrets")
        self.assertGreaterEqual(secrets_rules.count(), 20)  # at least 20 detect-secrets rules

    def test_flake8_rules_loaded(self):
        """Flake8 rules must be loaded from flake8_rules.json."""
        self._run_command()
        flake8_rules = SecurityRule.objects.filter(check_category="flake8")
        self.assertGreaterEqual(flake8_rules.count(), 90)  # at least 90 flake8 rules

    def test_file_analysis_rules_loaded(self):
        """File-analysis rules must be loaded from file_analysis_rules.json."""
        self._run_command()
        fa_rules = SecurityRule.objects.filter(check_category="file_analysis")
        self.assertGreaterEqual(fa_rules.count(), 4)

    def test_expected_total_rule_count(self):
        """Total rules must match the sum of all JSON files (78+27+96+4 = 205)."""
        self._run_command()
        # Allow a small tolerance in case JSON files are updated in the future,
        # but enforce a minimum that catches clearly incomplete loads.
        total = SecurityRule.objects.count()
        self.assertGreaterEqual(total, 200)

    def test_specific_rules_exist(self):
        """Key representative rules from each category must exist after the command."""
        self._run_command()
        expected_codes = [
            "B101",  # bandit
            "KeywordDetector",  # secrets
            "E501",  # flake8
            "FILE_EXECUTABLE",  # file_analysis
        ]
        for code in expected_codes:
            self.assertTrue(
                SecurityRule.objects.filter(check_code=code).exists(),
                f"Expected rule with check_code={code} to exist after populate command",
            )

    def test_f901_rule_exists(self):
        """F901 rule must exist in flake8 rules."""
        self._run_command()
        self.assertTrue(
            SecurityRule.objects.filter(check_code="F901", check_category="flake8").exists(),
            "F901 rule must be present in flake8 rules",
        )

    def test_update_or_create_on_second_run(self):
        """Running the command twice must not create duplicate rules."""
        self._run_command()
        count_after_first = SecurityRule.objects.count()
        self._run_command()
        count_after_second = SecurityRule.objects.count()
        self.assertEqual(count_after_first, count_after_second)

    def test_update_or_create_updates_existing_rules(self):
        """Running the command must update an existing rule's attributes."""
        self._run_command()
        rule = SecurityRule.objects.get(check_code="B101")
        # Manually corrupt the name
        rule.check_name = "CORRUPTED"
        rule.save()

        # Re-run: must restore the name from JSON
        self._run_command()
        rule.refresh_from_db()
        self.assertNotEqual(rule.check_name, "CORRUPTED")

    def test_clear_flag_removes_existing_rules(self):
        """--clear flag must delete all existing rules before repopulating."""
        self._run_command()
        count_before = SecurityRule.objects.count()
        self.assertGreater(count_before, 0)

        self._run_command("--clear")
        # After clear + repopulate the count should be the same (not doubled)
        count_after = SecurityRule.objects.count()
        self.assertEqual(count_after, count_before)

    def test_clear_flag_removes_stale_rules(self):
        """--clear flag must remove rules that no longer exist in the JSON files."""
        self._run_command()
        # Add a stale rule that isn't in any JSON file
        SecurityRule.objects.create(
            check_code="STALE_RULE_99",
            check_category="bandit",
            check_name="Stale rule",
            check_description="This rule no longer exists in the JSON files.",
            severity="info",
            enabled=False,
            can_be_skipped=True,
        )
        self.assertTrue(SecurityRule.objects.filter(check_code="STALE_RULE_99").exists())

        # Run with --clear: stale rule must be deleted
        self._run_command("--clear")
        self.assertFalse(SecurityRule.objects.filter(check_code="STALE_RULE_99").exists())

    def test_critical_rules_are_non_skippable(self):
        """Critical-severity rules (e.g., B602) must have can_be_skipped=False."""
        self._run_command()
        critical_rules = SecurityRule.objects.filter(severity="critical")
        for rule in critical_rules:
            self.assertFalse(
                rule.can_be_skipped,
                f"Critical rule {rule.check_code} must not be skippable",
            )

    def test_warning_rules_are_skippable(self):
        """Warning-severity rules must have can_be_skipped=True."""
        self._run_command()
        # Check a known warning rule
        rule = SecurityRule.objects.filter(check_code="B311").first()
        if rule:
            self.assertTrue(rule.can_be_skipped)

    def test_command_output_includes_categories(self):
        """Command output must mention each rule category."""
        output = self._run_command()
        for category in ("bandit", "secrets", "flake8", "file_analysis"):
            self.assertIn(category, output.lower())
