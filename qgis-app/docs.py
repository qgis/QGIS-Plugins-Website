from django.shortcuts import render
from django.utils.translation import gettext_lazy as _


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
    Renders the docs_security_scanning page
    """
    return render(
        request,
        "flatpages/docs_security_scanning.html",
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


def docs_guidelines(request):
    """
    Renders the Plugin Publishing Guidelines index page
    """
    return render(
        request,
        "flatpages/docs_guidelines.html",
        {},
    )


def docs_guidelines_metadata(request):
    """
    Renders the Requirements guidelines page
    """
    return render(
        request,
        "flatpages/docs_guidelines_metadata.html",
        {},
    )


def docs_guidelines_quality(request):
    """
    Renders the Plugin Quality guidelines page
    """
    return render(
        request,
        "flatpages/docs_guidelines_quality.html",
        {},
    )


def docs_guidelines_compatibility(request):
    """
    Renders the Version Compatibility guidelines page
    """
    return render(
        request,
        "flatpages/docs_guidelines_compatibility.html",
        {},
    )


def docs_guidelines_promotion(request):
    """
    Renders the Promoting Your Plugin guidelines page
    """
    return render(
        request,
        "flatpages/docs_guidelines_promotion.html",
        {},
    )


def docs_guidelines_policy(request):
    """
    Renders the Repository Policy guidelines page
    """
    return render(
        request,
        "flatpages/docs_guidelines_policy.html",
        {},
    )
