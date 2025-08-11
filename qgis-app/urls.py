import simplemenu
from django.conf import settings
from django.urls import re_path as url

# Uncomment the next two lines to enable the admin:
from django.contrib import admin
from django.contrib.flatpages.models import FlatPage
from django.urls import include, path
from django.views.generic.base import RedirectView
from django.views.static import serve
from drf_yasg import openapi
from drf_yasg.views import get_schema_view

# to find users app views
# from users.views import *
from homepage import homepage
from docs import docs_publish, docs_approval, docs_faq
from rest_framework import permissions

admin.autodiscover()


schema_view = get_schema_view(
    openapi.Info(
        title="Hub API",
        default_version="v1",
        description="Hub API for sharing files application",
        terms_of_service="https://www.google.com/policies/terms/",
        contact=openapi.Contact(email="email@example.com"),
        license=openapi.License(name="CC"),
    ),
    public=True,
    permission_classes=(permissions.AllowAny,),
)

urlpatterns = [
    # Example:
    # (r'^qgis/', include('qgis.foo.urls')),
    # Uncomment the admin/doc line below to enable admin documentation:
    # (r'^admin/doc/', include('django.contrib.admindocs.urls')),
    # Uncomment the next line to enable the admin:
    url(r"^admin/", admin.site.urls),
    # ABP: plugins app
    url(r"^plugins/", include("plugins.urls")),
    url(r"^search/", include("custom_haystack_urls")),
    url(r"^search/", include("haystack.urls")),
    # ABP: autosuggest for tags
    url(r"^taggit_autosuggest/", include("taggit_autosuggest.urls")),
    url(r"^userexport/", include("userexport.urls")),
]

# ABP: temporary home page
# urlpatterns += patterns('django.views.generic.simple',
#    url(r'^$', 'direct_to_template', {'template': 'index.html'}, name = 'index'),
# )


# serving static media
from django.conf.urls.static import static

if settings.SERVE_STATIC_MEDIA:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)


# auth
urlpatterns += [
    path("accounts/", include("django.contrib.auth.urls")),
]

# tinymce
# urlpatterns += [
#     url(r"^tinymce/", include("tinymce.urls")),
# ]


# Home and documentation pages
urlpatterns += [
    url(r"^$", homepage, name="homepage"),
    url(r"^docs/publish", docs_publish, name="docs_publish"),
    url(r"^docs/approval", docs_approval, name="docs_approval"),
    url(r"^docs/faq", docs_faq, name="docs_faq"),
]



if settings.DEBUG:
    import debug_toolbar

    urlpatterns += [
        url(r"^__debug__/", include(debug_toolbar.urls)),
    ]

simplemenu.register(
    "/admin/",
    # All plugins
    "/plugins/",
    # My plugins
    "/plugins/my",
    # Unapproved plugins
    "/plugins/unapproved/",
    "/plugins/feedback_completed/",
    "/plugins/feedback_received/",
    "/plugins/feedback_pending/",
    # New plugins
    "/plugins/fresh/",
    "/plugins/latest/",
    # Top plugins
    "/plugins/featured/",
    "/plugins/popular/",
    "/plugins/most_voted/",
    "/plugins/most_downloaded/",
    "/plugins/most_rated/",
    # Category
    "/plugins/stable/",
    "/plugins/experimental/",
    "/plugins/server/",
    "/plugins/deprecated/",
    FlatPage.objects.all(),
    simplemenu.models.URLItem.objects.all(),
)
