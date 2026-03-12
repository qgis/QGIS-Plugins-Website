"""
Asynchronous Celery task for running security and QA checks on plugin versions.

This task is queued immediately after a plugin is uploaded and processes all
security checks (Bandit, Secrets Detection, Code Quality, File Permissions,
Suspicious Files) in the background.

Upload flow:
1. Plugin uploaded → validation_status='validating', approved=False
2. This task is queued
3. All checks run asynchronously
4. Results stored, validation_status updated:
   - 'validated': no critical issues → available for approval/auto-approval
   - 'blocked': critical issues found → unavailable until re-upload
5. Email sent to maintainer(s) with results
"""

import logging

from celery import shared_task
from celery.utils.log import get_task_logger
from django.conf import settings
from django.contrib.sites.models import Site
from django.utils.translation import gettext_lazy as _

logger = get_task_logger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def run_security_scan_task(self, plugin_version_pk, is_manual=False):
    """
    Run security scan on a plugin version asynchronously.

    Args:
        plugin_version_pk: Primary key of the PluginVersion to scan
        is_manual: If True, this is a manual re-scan on an existing version.
                   Manual scans are informational only and do not change
                   the plugin's approval or validation status.
    """
    from plugins.models import (
        VALIDATION_STATUS_BLOCKED,
        VALIDATION_STATUS_VALIDATED,
        PluginVersion,
    )
    from plugins.security_utils import run_security_scan

    try:
        plugin_version = PluginVersion.objects.select_related(
            "plugin", "created_by"
        ).get(pk=plugin_version_pk)
    except PluginVersion.DoesNotExist:
        logger.error(f"PluginVersion {plugin_version_pk} not found, aborting scan")
        return

    plugin = plugin_version.plugin
    logger.info(
        f"Starting security scan for {plugin.package_name} v{plugin_version.version} "
        f"(manual={is_manual})"
    )

    # Run the security scan (synchronous scan running in the worker)
    security_scan = run_security_scan(plugin_version)

    if security_scan is None:
        # Scan failed to run — treat as validated to avoid blocking on tool errors
        logger.warning(
            f"Security scan failed for {plugin.package_name} v{plugin_version.version}, "
            "treating as validated"
        )
        if not is_manual:
            plugin_version.validation_status = VALIDATION_STATUS_VALIDATED
            _maybe_auto_approve(plugin_version)
            plugin_version.save()
            _send_validation_results_email(plugin_version, security_scan=None)
            if not plugin_version.approved:
                _notify_staff_for_review(plugin_version)
        return

    # Determine blocking status: Bandit and Secrets Detection are blocking
    has_critical_issues = security_scan.critical_count > 0

    if is_manual:
        # Manual scans are informational only — never change status or approval
        logger.info(
            f"Manual scan complete for {plugin.package_name} v{plugin_version.version}: "
            f"critical={security_scan.critical_count}"
        )
        return

    if has_critical_issues:
        plugin_version.validation_status = VALIDATION_STATUS_BLOCKED
        logger.warning(
            f"Plugin {plugin.package_name} v{plugin_version.version} BLOCKED: "
            f"{security_scan.critical_count} critical issue(s) found"
        )
    else:
        plugin_version.validation_status = VALIDATION_STATUS_VALIDATED
        _maybe_auto_approve(plugin_version)
        logger.info(
            f"Plugin {plugin.package_name} v{plugin_version.version} validated successfully"
        )

    plugin_version.save()

    # Send validation results email to maintainer(s)
    _send_validation_results_email(plugin_version, security_scan)

    # Notify staff approvers when a non-trusted plugin is ready for review
    if (
        plugin_version.validation_status == VALIDATION_STATUS_VALIDATED
        and not plugin_version.approved
    ):
        _notify_staff_for_review(plugin_version)


def _maybe_auto_approve(plugin_version):
    """
    Auto-approve the version if the uploader is trusted or the plugin
    already has at least one approved version.
    """
    created_by = plugin_version.created_by
    plugin = plugin_version.plugin

    if created_by and (
        created_by.has_perm("plugins.can_approve") or plugin.approved
    ):
        plugin_version.approved = True
        logger.info(
            f"Auto-approving {plugin.package_name} v{plugin_version.version} "
            f"(trusted={created_by.has_perm('plugins.can_approve')}, "
            f"plugin_approved={plugin.approved})"
        )


def _send_validation_results_email(plugin_version, security_scan):
    """
    Send Stage 2 email: validation results to the plugin maintainer(s).
    """
    if getattr(settings, "DEBUG", False):
        logger.debug("Validation results email not sent (DEBUG=True)")
        return

    from django.core.mail import send_mail

    plugin = plugin_version.plugin
    recipients = [u.email for u in plugin.editors if u.email]
    if not recipients:
        logger.warning(
            f"No recipients found for validation results email for {plugin.package_name}"
        )
        return

    domain = Site.objects.get_current().domain
    mail_from = settings.DEFAULT_FROM_EMAIL
    version_url = f"https://{domain}{plugin_version.get_absolute_url()}"
    security_url = f"{version_url}#security-tab"
    docs_url = f"https://{domain}/docs/security-scanning"

    if security_scan is None:
        subject = _("Plugin Validation Results: %(name)s v%(version)s") % {
            "name": plugin.name,
            "version": plugin_version.version,
        }
        message = _(
            "Plugin validation for %(name)s v%(version)s completed.\n\n"
            "The security scan could not be completed due to a tool error, "
            "but your plugin has been made available for approval.\n\n"
            "Plugin details: %(url)s\n"
        ) % {
            "name": plugin.name,
            "version": plugin_version.version,
            "url": version_url,
        }
    elif plugin_version.validation_status == "validated":
        auto_approved = plugin_version.approved
        subject = _("Plugin Validation Results: %(name)s v%(version)s - All Checks Passed") % {
            "name": plugin.name,
            "version": plugin_version.version,
        }
        if auto_approved:
            status_msg = _(
                "Your plugin has been automatically approved and is now available for download."
            )
        else:
            status_msg = _(
                "Your plugin is ready for review by an approver."
            )
        message = _(
            "Good news! All security and quality checks passed for your plugin.\n\n"
            "Plugin: %(name)s\n"
            "Version: %(version)s\n"
            "Status: %(status)s\n\n"
            "Summary:\n"
            "  - Checks passed: %(passed)s / %(total)s\n"
            "  - Files scanned: %(files)s\n\n"
            "View detailed results: %(security_url)s\n"
        ) % {
            "name": plugin.name,
            "version": plugin_version.version,
            "status": status_msg,
            "passed": security_scan.passed_checks,
            "total": security_scan.total_checks,
            "files": security_scan.files_scanned,
            "security_url": security_url,
        }
    else:
        # blocked
        subject = _("Plugin Validation Results: %(name)s v%(version)s - Critical Issues Found") % {
            "name": plugin.name,
            "version": plugin_version.version,
        }
        # Build critical issues details
        critical_details = _build_critical_issues_text(security_scan)
        message = _(
            "Critical security issues were found in your plugin and it has been BLOCKED.\n\n"
            "Plugin: %(name)s\n"
            "Version: %(version)s\n"
            "Status: BLOCKED - Not available for approval or download until issues are resolved\n\n"
            "Critical issues found:\n"
            "%(critical_details)s\n"
            "To resolve this:\n"
            "1. Fix the critical issues listed above\n"
            "2. Upload a new version of your plugin\n"
            "3. The new version will be automatically re-scanned\n\n"
            "View detailed scan results: %(security_url)s\n"
            "Security best practices: %(docs_url)s\n"
        ) % {
            "name": plugin.name,
            "version": plugin_version.version,
            "critical_details": critical_details,
            "security_url": security_url,
            "docs_url": docs_url,
        }

    try:
        send_mail(
            str(subject),
            str(message),
            mail_from,
            recipients,
            fail_silently=True,
        )
        logger.info(
            f"Validation results email sent for {plugin.package_name} v{plugin_version.version} "
            f"to {recipients}"
        )
    except Exception as e:
        logger.error(f"Failed to send validation results email: {e}")


def _build_critical_issues_text(security_scan):
    """Build a text summary of critical issues from the scan report."""
    lines = []
    for check in security_scan.scan_report.get("checks", []):
        if not check.get("passed") and check.get("severity") == "critical":
            lines.append(f"\n[{check['name']}] - {check['issues_found']} issue(s)")
            for detail in check.get("details", [])[:5]:
                file_info = detail.get("file", "N/A")
                line_info = detail.get("line", "")
                msg = detail.get("message", "")
                if line_info:
                    lines.append(f"  - {file_info}:{line_info}: {msg}")
                else:
                    lines.append(f"  - {file_info}: {msg}")
    return "\n".join(lines) if lines else _("No details available.")


def _notify_staff_for_review(plugin_version):
    """
    Notify staff approvers that a plugin is ready for review
    (equivalent to version_notify but triggered from the task).
    """
    if getattr(settings, "DEBUG", False):
        return

    from django.core.mail import send_mail

    plugin = plugin_version.plugin
    domain = Site.objects.get_current().domain
    mail_from = settings.DEFAULT_FROM_EMAIL

    notification_group = getattr(
        settings, "NOTIFICATION_RECIPIENTS_GROUP_NAME", "Plugin Notification Recipients"
    )
    from django.contrib.auth.models import User

    recipients = [
        u.email
        for u in User.objects.filter(
            groups__name=notification_group,
            is_staff=True,
            email__isnull=False,
        ).exclude(email="")
    ]

    if not recipients:
        logger.warning(
            f"No staff recipients for review notification of {plugin.package_name}"
        )
        return

    try:
        send_mail(
            str(
                _("A new plugin version is ready for review: %(plugin)s v%(version)s")
                % {"plugin": plugin.name, "version": plugin_version.version}
            ),
            str(
                _(
                    "Plugin %(name)s version %(version)s has passed all security checks "
                    "and is ready for approval.\n\n"
                    "Uploaded by: %(user)s\n"
                    "Link: http://%(domain)s%(url)s\n"
                )
                % {
                    "name": plugin.name,
                    "version": plugin_version.version,
                    "user": plugin_version.created_by,
                    "domain": domain,
                    "url": plugin_version.get_absolute_url(),
                }
            ),
            mail_from,
            recipients,
            fail_silently=True,
        )
    except Exception as e:
        logger.error(f"Failed to send staff review notification: {e}")
