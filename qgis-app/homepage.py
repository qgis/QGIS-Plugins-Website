from django.contrib.flatpages.models import FlatPage
from django.shortcuts import render
from django.template import RequestContext
from django.utils.translation import gettext_lazy as _
from plugins.models import Plugin



def homepage(request):
    """
    Renders the home page
    """
    latest = Plugin.latest_objects.all()[:5]
    featured = Plugin.featured_objects.all()[:5]
    popular = Plugin.popular_objects.all()[:5]
    try:
        content = FlatPage.objects.get(url="/").content
    except FlatPage.DoesNotExist:
        content = _('To add content here, create a FlatPage with url="/"')

    return render(
        request,
        "flatpages/homepage.html",
        {
            "featured": featured,
            "latest": latest,
            "popular": popular,
            "content": content,
            "title": "QGIS plugins web portal"
        },
    )

def documentation(request):
    """
    Renders the documentation page
    """
    return render(
        request,
        "flatpages/documentation.html",
        {},
    )