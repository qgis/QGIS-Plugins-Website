# -*- coding: utf-8 -*-
"""
Read-only public API exposing the platform's enabled security rules.

This is the single source of rule truth for the standalone CLI (see
tools/security-scan-cli/) so that locally-run security checks always reflect
the rules configured here, with no rule drift.

    GET /plugins/api/security-rules/
"""
from importlib.metadata import PackageNotFoundError, version

from django.http import HttpRequest, JsonResponse
from django.views.decorators.cache import cache_page
from django.views.decorators.http import require_GET

from plugins.models import SecurityRule

# Distribution names of the analysis tools, as pinned in
# dockerize/docker/REQUIREMENTS.txt. Reported so the CLI can warn when a
# developer's locally-installed tool versions differ from the platform's.
SECURITY_TOOL_DISTRIBUTIONS = ["bandit", "detect-secrets", "flake8"]


def _tool_versions() -> dict:
    """Return the actually-installed versions of the analysis tools."""
    versions = {}
    for dist in SECURITY_TOOL_DISTRIBUTIONS:
        try:
            versions[dist] = version(dist)
        except PackageNotFoundError:
            versions[dist] = None
    return versions


@require_GET
@cache_page(60 * 5)
def security_rules_api(request: HttpRequest) -> JsonResponse:
    """
    Expose the enabled security rules plus the platform's tool versions.

    Public and read-only: no authentication and no plugin record required, so
    authors can run checks locally before a plugin even exists on the platform.
    """
    enabled_rules = SecurityRule.objects.filter(enabled=True).order_by(
        "check_category", "check_code"
    )
    rules = [
        {
            "check_code": rule.check_code,
            "check_category": rule.check_category,
            "check_name": rule.check_name,
            "severity": rule.severity,
            "enabled": rule.enabled,
            "can_be_skipped": rule.can_be_skipped,
        }
        for rule in enabled_rules
    ]

    # The full list of secrets plugin codes lets the CLI disable non-enabled
    # detect-secrets plugins without any database access.
    secrets_plugins = list(
        SecurityRule.objects.filter(check_category="secrets")
        .order_by("check_code")
        .values_list("check_code", flat=True)
    )

    return JsonResponse(
        {
            "rules": rules,
            "secrets_plugins": secrets_plugins,
            "tool_versions": _tool_versions(),
        }
    )
