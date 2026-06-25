"""
Management command to populate the SecurityRule table with all known security
and quality check rules from Bandit, detect-secrets, flake8, and internal
file-analysis checks.

Rule data is loaded from JSON files in the data/ subdirectory alongside this
command. Edit those files to add, remove, or adjust rules rather than
modifying this command.

Sources:
  Bandit:          https://bandit.readthedocs.io/en/latest/plugins/index.html
                   https://bandit.readthedocs.io/en/latest/blacklists/index.html
  detect-secrets:  https://pypi.org/project/detect-secrets/
  flake8:          https://www.flake8rules.com/
  file_analysis:   Internal custom checks

Run with: python manage.py populate_security_rules
"""

import json
import os

from django.core.management.base import BaseCommand

from plugins.models import SecurityRule

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")

DATA_FILES = [
    ("bandit", "bandit_rules.json"),
    ("secrets", "secrets_rules.json"),
    ("flake8", "flake8_rules.json"),
    ("file_analysis", "file_analysis_rules.json"),
]


class Command(BaseCommand):
    help = "Populate SecurityRule table with all known security and quality check rules"

    def add_arguments(self, parser):
        parser.add_argument(
            "--clear",
            action="store_true",
            help="Clear existing rules before populating",
        )

    def handle(self, *args, **options):
        if options["clear"]:
            count = SecurityRule.objects.all().count()
            SecurityRule.objects.all().delete()
            self.stdout.write(
                self.style.WARNING(f"Cleared {count} existing security rules")
            )

        created_count = 0
        updated_count = 0

        for category, filename in DATA_FILES:
            filepath = os.path.join(DATA_DIR, filename)
            with open(filepath, encoding="utf-8") as f:
                data = json.load(f)

            rules = data.get("rules", [])
            self.stdout.write(
                f"\n[{category}] Loading {len(rules)} rules from {filename}"
            )

            for rule_data in rules:
                rule, created = SecurityRule.objects.update_or_create(
                    check_code=rule_data["check_code"],
                    defaults={
                        "check_category": category,
                        "check_name": rule_data["check_name"],
                        "check_description": rule_data["check_description"],
                        "severity": rule_data["severity"],
                        "enabled": rule_data["enabled"],
                        "can_be_skipped": rule_data["can_be_skipped"],
                    },
                )
                if created:
                    created_count += 1
                    self.stdout.write(
                        f"  + {rule.check_code}: {rule.check_name}"
                    )
                else:
                    updated_count += 1
                    self.stdout.write(
                        self.style.WARNING(
                            f"  ~ {rule.check_code}: {rule.check_name}"
                        )
                    )

        self.stdout.write(
            self.style.SUCCESS(
                f"\nDone! Created: {created_count}, Updated: {updated_count}"
            )
        )
        self.stdout.write("\nSeverity defaults:")
        self.stdout.write(
            "  critical → enabled=True,  can_be_skipped=False (mandatory)"
        )
        self.stdout.write(
            "  warning  → enabled=True,  can_be_skipped=True  (skippable)"
        )
        self.stdout.write(
            "  info     → enabled=False, can_be_skipped=True  (disabled)"
        )
        self.stdout.write(
            "\nAdministrators can adjust individual rule configurations at any time."
        )


