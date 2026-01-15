"""
Utility functions for running security scans on plugin versions
"""

import logging

from plugins.models import PluginVersionSecurityScan
from plugins.security_scanner import PluginSecurityScanner

logger = logging.getLogger(__name__)


def run_security_scan(plugin_version):
    """
    Run security scan on a plugin version and save results

    Args:
        plugin_version: PluginVersion instance

    Returns:
        PluginVersionSecurityScan instance or None if scan fails
    """
    try:
        # Get the package file path
        package_path = plugin_version.package.path

        # Initialize and run scanner
        scanner = PluginSecurityScanner(package_path)
        report = scanner.scan()

        # Create or update security scan record
        security_scan, created = PluginVersionSecurityScan.objects.update_or_create(
            plugin_version=plugin_version,
            defaults={
                "total_checks": report["summary"]["total_checks"],
                "passed_checks": report["summary"]["passed"],
                "warning_count": report["summary"]["warnings"],
                "critical_count": report["summary"]["critical"],
                "info_count": report["summary"]["info"],
                "files_scanned": report["summary"]["files_scanned"],
                "total_issues": report["summary"]["total_issues"],
                "scan_report": report,
            },
        )

        logger.info(
            f"Security scan {'created' if created else 'updated'} for "
            f"{plugin_version.plugin.package_name} v{plugin_version.version}"
        )

        return security_scan

    except Exception as e:
        logger.error(
            f"Error running security scan for {plugin_version.plugin.package_name} "
            f"v{plugin_version.version}: {str(e)}"
        )
        return None


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

    return badges.get(status, badges["passed"])
