# -*- coding: utf-8 -*-
from django.urls import re_path as url
from django.contrib.auth.decorators import login_required, user_passes_test
from django.utils.translation import gettext_lazy as _
from plugins.models import Plugin, PluginVersion
from plugins.views import *
from rpc4django.views import serve_rpc_request

# Plugins filtered views (need user parameter from request)
urlpatterns = [
    # XML
    url(r"^plugins_new.xml$", xml_plugins_new, {}, name="xml_plugins_new"),
    url(r"^plugins.xml$", xml_plugins, {}, name="xml_plugins"),
    url(
        r"^plugins_(?P<qg_version>\d+\.\d+).xml$",
        xml_plugins,
        {},
        name="xml_plugins_version_filtered_cached",
    ),
    url(
        r"^version_filtered/(?P<qg_version>\d+\.\d+).xml$",
        xml_plugins,
        {},
        name="xml_plugins_version_filtered_uncached",
    ),
    url(r"^tags/(?P<tags>[^\/]+)/$", TagsPluginsList.as_view(), name="tags_plugins"),
    url(r"^add/$", plugin_upload, {}, name="plugin_upload"),
    url(r"^user/(?P<username>\w+)/block/$", user_block, {}, name="user_block"),
    url(r"^user/(?P<username>\w+)/unblock/$", user_unblock, {}, name="user_unblock"),
    url(r"^user/(?P<username>\w+)/trust/$", user_trust, {}, name="user_trust"),
    url(r"^user/(?P<username>\w+)/untrust/$", user_untrust, {}, name="user_untrust"),
    url(
        r"^(?P<package_name>[A-Za-z][A-Za-z0-9-_]+)/manage/$",
        plugin_manage,
        {},
        name="plugin_manage",
    ),
    url(
        r"^(?P<package_name>[A-Za-z][A-Za-z0-9-_]+)/delete/$",
        plugin_delete,
        {},
        name="plugin_delete",
    ),
    url(
        r"^(?P<package_name>[A-Za-z][A-Za-z0-9-_]+)/update/$",
        plugin_update,
        {},
        name="plugin_update",
    ),
    url(
        r"^(?P<package_name>[A-Za-z][A-Za-z0-9-_]+)/tokens/$",
        PluginTokenListView.as_view(),
        name="plugin_token_list",
    ),
    url(
        r"^(?P<package_name>[A-Za-z][A-Za-z0-9-_]+)/tokens/(?P<pk>\d+)/$",
        PluginTokenDetailView.as_view(),
        name="plugin_token_detail",
    ),
    url(
        r"^(?P<package_name>[A-Za-z][A-Za-z0-9-_]+)/tokens/create/$",
        plugin_token_create,
        {},
        name="plugin_token_create",
    ),
    url(
        r"^(?P<package_name>[A-Za-z][A-Za-z0-9-_]+)/tokens/(?P<token_id>\d+)/update$",
        plugin_token_update,
        {},
        name="plugin_token_update",
    ),
    url(
        r"^(?P<package_name>[A-Za-z][A-Za-z0-9-_]+)/tokens/(?P<token_id>[^\/]+)/delete/$",
        plugin_token_delete,
        {},
        name="plugin_token_delete",
    ),
    # Uncomment the following lines when ready to use featured plugins
    # url(
    #     r"^(?P<package_name>[A-Za-z][A-Za-z0-9-_]+)/set_featured/$",
    #     plugin_set_featured,
    #     {},
    #     name="plugin_set_featured",
    # ),
    # url(
    #     r"^(?P<package_name>[A-Za-z][A-Za-z0-9-_]+)/unset_featured/$",
    #     plugin_unset_featured,
    #     {},
    #     name="plugin_unset_featured",
    # ),
    url(
        r"^user/(?P<username>\w+)/admin$",
        UserDetailsPluginsList.as_view(),
        name="user_details",
    ),
    url(r"^$", PluginsList.as_view(
        additional_context={
            "title": _("All Plugins"),
            "description": _("List of all approved plugins."),
        }
    ), name="approved_plugins"),
    url(
        r"^my$",
        login_required(
            MyPluginsList.as_view(
                additional_context={
                    "title": _("My Plugins"),
                    "description": _("List of plugins created or maintained by the current user."),
                }
            )
        ),
        name="my_plugins",
    ),
    # Uncomment the following lines when ready to use featured plugins
    # url(
    #     r"^featured/$",
    #     PluginsList.as_view(
    #         queryset=Plugin.featured_objects.all(),
    #         additional_context={
    #             "title": _("Featured Plugins"),
    #             "description": _("List of approved plugins with the 'featured' flags set."),
    #         },
    #     ),
    #     name="featured_plugins",
    # ),
    url(r"^user/(?P<username>\w+)/$", UserPluginsList.as_view(), name="user_plugins"),
    url(
        r"^server/$",
        PluginsList.as_view(
            queryset=Plugin.server_objects.all(),
            additional_context={
                "title": _("QGIS Server Plugins"),
                "description": _("List of plugins specifically for QGIS Server."),
            },
        ),
        name="server_plugins",
    ),
    url(
        r"^unapproved/$",
        PluginsList.as_view(
            queryset=Plugin.unapproved_objects.all().order_by("-latest_version_date"),
            additional_context={
                "title": _("Unapproved Plugins"),
                "description": _("List of plugins that are not yet approved and not deprecated."),
            },
        ),
        name="unapproved_plugins",
    ),
    url(
        r"^deprecated/$",
        PluginsList.as_view(
            queryset=Plugin.deprecated_objects.all(),
            additional_context={
                "title": _("Deprecated Plugins"),
                "description": _("List of plugins that are no longer maintained or recommended."),
            },
        ),
        name="deprecated_plugins",
    ),
    url(
        r"^fresh/$",
        PluginsList.as_view(
            queryset=Plugin.fresh_objects.all(),
            additional_context={
                "title": _("New plugins"),
                "description": _("List of plugins that have been created in the last 30 days."),
            },
        ),
        name="fresh_plugins",
    ),
    url(
        r"^latest/$",
        PluginsList.as_view(
            queryset=Plugin.latest_objects.all(),
            additional_context={
                "title": _("Updated plugins"),
                "description": _("List of plugins that have been updated in the last 30 days."),
            },
        ),
        name="latest_plugins",
    ),
    url(
        r"^stable/$",
        PluginsList.as_view(
            queryset=Plugin.stable_objects.all(),
            additional_context={
                "title": _("Stable Plugins"),
                "description": _("List of approved plugins with at least one stable version."),
            },
        ),
        name="stable_plugins",
    ),
    url(
        r"^experimental/$",
        PluginsList.as_view(
            queryset=Plugin.experimental_objects.all(),
            additional_context={
                "title": _("Experimental Plugins"),
                "description": _("List of approved plugins with at least one experimental version."),
            },
        ),
        name="experimental_plugins",
    ),
    url(
        r"^popular/$",
        PluginsList.as_view(
            queryset=Plugin.popular_objects.all(),
            additional_context={
                "title": _("Popular Plugins"),
                "description": _(
                    "List of approved plugins sorted by popularity. "
                    "Popularity is calculated by the number of "
                    "downloads and votes."
                ),
            },
        ),
        name="popular_plugins",
    ),
    url(
        r"^most_voted/$",
        PluginsList.as_view(
            queryset=Plugin.most_voted_objects.all(),
            additional_context={
                "title": _("Most Voted Plugins"),
                "description": _("List of approved plugins sorted by the number of votes."),
            },
        ),
        name="most_voted_plugins",
    ),
    url(
        r"^most_downloaded/$",
        PluginsList.as_view(
            queryset=Plugin.most_downloaded_objects.all(),
            additional_context={
                "title": _("Most Downloaded Plugins"),
                "description": _("List of approved plugins sorted by the number of downloads."),
            },
        ),
        name="most_downloaded_plugins",
    ),
    url(
        r"^most_rated/$",
        PluginsList.as_view(
            queryset=Plugin.most_rated_objects.all(),
            additional_context={
                "title": _("Most Rated Plugins"),
                "description": _("List of approved plugins sorted by the number of ratings."),
            },
        ),
        name="most_rated_plugins",
    ),
    url(
        r"^feedback_completed/$",
        FeedbackCompletedPluginsList.as_view(
            additional_context={
                "title": _("Reviewed Plugins (Resolved)"),
                "description": _("List of unapproved plugins with resolved feedback."),
            }
        ),
        name="feedback_completed_plugins",
    ),
    url(
        r"^feedback_pending/$",
        FeedbackPendingPluginsList.as_view(
            additional_context={
                "title": _("Awaiting review"),
                "description": _("List of unapproved plugins awaiting feedback review."),
            }
        ),
        name="feedback_pending_plugins",
    ),
    url(
        r"^feedback_received/$",
        FeedbackReceivedPluginsList.as_view(
            additional_context={
                "title": _("Reviewed Plugins (Pending)"),
                "description": _("List of unapproved plugins with pending feedback."),
            }
        ),
        name="feedback_received_plugins",
    ),
    url(
        r"^author/(?P<author>[^/]+)/$",
        AuthorPluginsList.as_view(),
        name="author_plugins",
    ),
]


# User management
urlpatterns += [
    url(
        r"^user/(?P<username>\w+)/manage/$",
        user_permissions_manage,
        {},
        name="user_permissions_manage",
    ),
]


# Version Management
urlpatterns += [
    url(
        r"^(?P<package_name>[A-Za-z][A-Za-z0-9-_]+)/version/(?P<version>[^\/]+)/manage/$",
        version_manage,
        {},
        name="version_manage",
    ),
    url(
        r"^(?P<package_name>[A-Za-z][A-Za-z0-9-_]+)/version/add/$",
        version_create,
        {},
        name="version_create",
    ),
    url(
        r"^api/(?P<package_name>[A-Za-z][A-Za-z0-9-_]+)/version/add/$",
        version_create_api,
        {},
        name="version_create_api",
    ),
    url(
        r"^(?P<package_name>[A-Za-z][A-Za-z0-9-_]+)/version/(?P<version>[^\/]+)/$",
        version_detail,
        {},
        name="version_detail",
    ),
    url(
        r"^(?P<package_name>[A-Za-z][A-Za-z0-9-_]+)/version/(?P<version>[^\/]+)/delete/$",
        version_delete,
        {},
        name="version_delete",
    ),
    url(
        r"^(?P<package_name>[A-Za-z][A-Za-z0-9-_]+)/version/(?P<version>[^\/]+)/update/$",
        version_update,
        {},
        name="version_update",
    ),
    url(
        r"^api/(?P<package_name>[A-Za-z][A-Za-z0-9-_]+)/version/(?P<version>[^\/]+)/update/$",
        version_update_api,
        {},
        name="version_update_api",
    ),
    url(
        r"^(?P<package_name>[A-Za-z][A-Za-z0-9-_]+)/version/(?P<version>[^\/]+)/download/$",
        version_download,
        {},
        name="version_download",
    ),
    url(
        r"^(?P<package_name>[A-Za-z][A-Za-z0-9-_]+)/version/(?P<version>[^\/]+)/approve/$",
        version_approve,
        {},
        name="version_approve",
    ),
    url(
        r"^(?P<package_name>[A-Za-z][A-Za-z0-9-_]+)/version/(?P<version>[^\/]+)/unapprove/$",
        version_unapprove,
        {},
        name="version_unapprove",
    ),
    url(
        r"^(?P<package_name>[A-Za-z][A-Za-z0-9-_]+)/version/(?P<version>[^\/]+)/feedback/$",
        version_feedback,
        {},
        name="version_feedback",
    ),
    url(
        r"^(?P<package_name>[A-Za-z][A-Za-z0-9-_]+)/version/(?P<version>[^\/]+)/feedback/update/$",
        version_feedback_update,
        {},
        name="version_feedback_update",
    ),
    url(
        r"^(?P<package_name>[A-Za-z][A-Za-z0-9-_]+)/version/(?P<version>[^\/]+)/feedback/(?P<feedback>[0-9]+)/delete/$",
        version_feedback_delete,
        {},
        name="version_feedback_delete",
    ),
    url(
        r"^(?P<package_name>[A-Za-z][A-Za-z0-9-_]+)/version/(?P<version>[^\/]+)/feedback/(?P<feedback>[0-9]+)/edit/$",
        version_feedback_edit,
        {},
        name="version_feedback_edit",
    ),
]

# RPC
urlpatterns += [
    # rpc4django will need to be in your Python path
    url(r"^RPC2/$", serve_rpc_request),
]


from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from django.views.decorators.http import require_POST

# plugin rating
from djangoratings.views import AddRatingFromModel

urlpatterns += [
    url(
        r"rate/(?P<object_id>\d+)/(?P<score>\d+)/",
        require_POST(csrf_protect(AddRatingFromModel())),
        {
            "app_label": "plugins",
            "model": "plugin",
            "field_name": "rating",
        },
        name="plugin_rate",
    ),
]


# Plugin detail (keep last)
urlpatterns += [
    url(
        r"^(?P<package_name>[A-Za-z][A-Za-z0-9-_]+)/$",
        PluginDetailView.as_view(
            slug_url_kwarg="package_name", slug_field="package_name",
        ),
        name="plugin_detail",
    ),
]
