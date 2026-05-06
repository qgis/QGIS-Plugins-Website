from django.shortcuts import render
from django.utils.translation import gettext_lazy as _
from plugins.security_utils import get_security_rules_grouped


def docs_publish(request):
    """
    Renders the docs_publish page
    """
    return render(
        request,
        "flatpages/docs_publish.html",
        {},
    )


def docs_approval(request):
    """
    Renders the docs_approval page
    """
    return render(
        request,
        "flatpages/docs_approval.html",
        {},
    )


def docs_faq(request):
    """
    Renders the docs_faq page
    """
    return render(
        request,
        "flatpages/docs_faq.html",
        {},
    )


def docs_security_scanning(request):
    """
    Renders the docs_security_scanning page.
    """
    return render(
        request,
        "flatpages/docs_security_scanning.html",
        {},
    )


def docs_security_config_files(request):
    """
    Renders the documentation page about using tool config files (.bandit,
    .secrets.baseline, .flake8) inside a plugin ZIP to influence scan results.
    """
    return render(
        request,
        "flatpages/docs_security_config_files.html",
        {},
    )


def docs_security_rules(request):
    """
    Renders the complete security rules reference page with live rule data from the database.
    """
    security_rules_grouped = get_security_rules_grouped()
    total_rules = sum(g["total_count"] for g in security_rules_grouped)
    total_enabled = sum(g["enabled_count"] for g in security_rules_grouped)
    total_skippable = sum(g["skippable_count"] for g in security_rules_grouped)
    total_disabled = total_rules - total_enabled
    total_critical = sum(g["critical_count"] for g in security_rules_grouped)
    total_warning = sum(g["warning_count"] for g in security_rules_grouped)
    total_info = sum(g["info_count"] for g in security_rules_grouped)
    return render(
        request,
        "flatpages/docs_security_rules.html",
        {
            "security_rules_grouped": security_rules_grouped,
            "total_rules": total_rules,
            "total_enabled": total_enabled,
            "total_skippable": total_skippable,
            "total_disabled": total_disabled,
            "total_critical": total_critical,
            "total_warning": total_warning,
            "total_info": total_info,
        },
    )


def docs_security_tools(request):
    """
    Renders the security tools detail page (Bandit, detect-secrets, Flake8, File Analysis,
    severity levels, understanding results, manual re-scan, local checks).
    """
    return render(
        request,
        "flatpages/docs_security_tools.html",
        {},
    )


def docs_security_skipping(request):
    """
    Renders the rule configuration and skipping guide (admin config, developer skipping,
    web form, REST API, requesting rule changes).
    """
    return render(
        request,
        "flatpages/docs_security_skipping.html",
        {},
    )


def docs_security_troubleshooting(request):
    """
    Renders the security scanning troubleshooting page (resolving blocked plugins,
    false positives, raising issues via GitHub, support).
    """
    return render(
        request,
        "flatpages/docs_security_troubleshooting.html",
        {},
    )


def docs_migrate_qgis4(request):
    """
    Renders the Migrate to QGIS 4 documentation page
    """
    return render(
        request,
        "flatpages/docs_migrate_qgis4.html",
        {},
    )
