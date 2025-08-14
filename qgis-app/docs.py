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
