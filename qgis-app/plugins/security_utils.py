"""
Utility functions for running security scans on plugin versions
"""

import logging

from django.utils import timezone
from plugins.models import (
    PluginVersionSecurityRuleSkip,
    PluginVersionSecurityScan,
    SecurityRule,
)
from plugins.security_scanner import PluginSecurityScanner

logger = logging.getLogger(__name__)


def run_security_scan(plugin_version, skipped_rule_ids=None):
    """
    Run security scan on a plugin version and save results

    Args:
        plugin_version: PluginVersion instance
        skipped_rule_ids: List of SecurityRule IDs that the developer chose to skip (optional)

    Returns:
        PluginVersionSecurityScan instance or None if scan fails
    """
    try:
        # Get the package file path
        package_path = plugin_version.package.path

        # Get all enabled security rules
        enabled_rules = list(SecurityRule.objects.filter(enabled=True))
        set(rule.id for rule in enabled_rules)

        # Track skipped rules
        skipped_rule_ids = skipped_rule_ids or []
        skipped_rule_codes = []

        # Filter out skipped rules from enabled rules
        if skipped_rule_ids:
            # Validate that skipped rules are actually enabled and skippable
            skippable_rules = SecurityRule.objects.filter(
                id__in=skipped_rule_ids, enabled=True, can_be_skipped=True
            )

            skipped_rule_ids_validated = set(rule.id for rule in skippable_rules)
            skipped_rule_codes = [rule.check_code for rule in skippable_rules]

            # Remove skipped rules from enabled rules
            enabled_rules = [
                rule
                for rule in enabled_rules
                if rule.id not in skipped_rule_ids_validated
            ]

            # Create PluginVersionSecurityRuleSkip records
            for rule in skippable_rules:
                PluginVersionSecurityRuleSkip.objects.get_or_create(
                    plugin_version=plugin_version,
                    security_rule=rule,
                    defaults={
                        "skipped_by": plugin_version.created_by,
                    },
                )

        # Initialize and run scanner with enabled rules
        scanner = PluginSecurityScanner(package_path, enabled_rules=enabled_rules)
        report = scanner.scan()
        config_files = report.get("config_files", [])

        # Create or update security scan record
        security_scan, created = PluginVersionSecurityScan.objects.update_or_create(
            plugin_version=plugin_version,
            defaults={
                "scanned_on": timezone.now(),
                "total_checks": report["summary"]["total_checks"],
                "passed_checks": report["summary"]["passed"],
                "warning_count": report["summary"]["warnings"],
                "critical_count": report["summary"]["critical"],
                "info_count": report["summary"]["info"],
                "files_scanned": report["summary"]["files_scanned"],
                "total_issues": report["summary"]["total_issues"],
                "enabled_rules_count": len(enabled_rules),
                "skipped_rules": skipped_rule_codes,
                "config_files_detected": config_files,
                "scan_report": report,
            },
        )

        logger.info(
            f"Security scan {'created' if created else 'updated'} for "
            f"{plugin_version.plugin.package_name} v{plugin_version.version} "
            f"(enabled rules: {len(enabled_rules)}, skipped: {len(skipped_rule_codes)})"
        )

        return security_scan

    except Exception as e:
        logger.error(
            f"Error running security scan for {plugin_version.plugin.package_name} "
            f"v{plugin_version.version}: {str(e)}"
        )
        return None


def get_security_rules_grouped():
    """
    Returns all security rules organised by category, with summary counts.
    Intended for passing to upload-form and docs templates.

    Returns:
        list of dicts, one per category, each containing:
            key, label, icon, rules (list), total_count,
            enabled_count, skippable_count,
            critical_count, warning_count, info_count
    """
    category_meta = [
        ("bandit", "Bandit Security", "fas fa-bug"),
        ("secrets", "Detect Secrets", "fas fa-key"),
        ("flake8", "Flake8 Quality", "fas fa-code"),
        ("file_analysis", "File Analysis", "fas fa-folder-open"),
    ]

    # Build severity ordering so Critical rules sort first
    severity_order = {"critical": 0, "warning": 1, "info": 2}

    all_rules = list(
        SecurityRule.objects.all().order_by("check_category", "check_code")
    )

    # Group by category
    groups = {}
    for rule in all_rules:
        cat = rule.check_category
        if cat not in groups:
            groups[cat] = []
        groups[cat].append(rule)

    result = []
    for cat_key, cat_label, cat_icon in category_meta:
        rules = groups.get(cat_key, [])
        # Sort by severity then code
        rules.sort(key=lambda r: (severity_order.get(r.severity, 9), r.check_code))

        total = len(rules)
        enabled = sum(1 for r in rules if r.enabled)
        skippable = sum(1 for r in rules if r.enabled and r.can_be_skipped)
        mandatory = sum(1 for r in rules if r.enabled and not r.can_be_skipped)
        critical = sum(1 for r in rules if r.severity == "critical")
        warning = sum(1 for r in rules if r.severity == "warning")
        info = sum(1 for r in rules if r.severity == "info")
        skippable_rules = [r for r in rules if r.enabled and r.can_be_skipped]

        result.append(
            {
                "key": cat_key,
                "label": cat_label,
                "icon": cat_icon,
                "rules": rules,
                "skippable_rules": skippable_rules,
                "total_count": total,
                "enabled_count": enabled,
                "skippable_count": skippable,
                "mandatory_count": mandatory,
                "critical_count": critical,
                "warning_count": warning,
                "info_count": info,
            }
        )

    return result


def get_scan_badge_info(security_scan):
    """
    Get badge information for display based on scan results

    Args:
        security_scan: PluginVersionSecurityScan instance

    Returns:
        dict with badge information (color, text, icon)
    """
    if not security_scan:
        return {
            "color": "secondary",
            "text": "Not Scanned",
            "icon": "fa-question-circle",
            "class": "badge-secondary",
        }

    status = security_scan.overall_status

    badges = {
        "passed": {
            "color": "success",
            "text": f"✓ All Checks Passed ({security_scan.pass_rate}%)",
            "icon": "fa-check-circle",
            "class": "badge-success",
        },
        "passed_with_config": {
            "color": "warning",
            "text": "⚙ Passed (config files used)",
            "icon": "fa-gear",
            "class": "badge-config",
        },
        "info": {
            "color": "info",
            "text": f"{security_scan.info_count} Info Items",
            "icon": "fa-info-circle",
            "class": "badge-info",
        },
        "warning": {
            "color": "warning",
            "text": f"{security_scan.warning_count} Warnings",
            "icon": "fa-exclamation-triangle",
            "class": "badge-warning",
        },
        "critical": {
            "color": "danger",
            "text": f"{security_scan.critical_count} Critical Issues",
            "icon": "fa-exclamation-circle",
            "class": "badge-danger",
        },
    }

    # Promote "passed" badge to "passed_with_config" when config files were used
    if status == "passed" and security_scan.config_files_detected:
        return badges["passed_with_config"]

    return badges.get(status, badges["passed"])
