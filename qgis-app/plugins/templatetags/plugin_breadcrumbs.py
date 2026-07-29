"""Breadcrumb trail for the per-plugin pages.

The trail is derived from the resolved URL rather than being set by each view, so
that every page hanging off a plugin gets breadcrumbs without touching its view.
Adding a new plugin sub-page only requires an entry in ``PLUGIN_PAGE_LABELS``.
"""

from django import template
from django.urls import NoReverseMatch, reverse
from django.utils.translation import gettext_lazy as _
from plugins.models import Plugin

register = template.Library()

# Leaf label per URL name. Pages absent from this map get no leaf crumb.
PLUGIN_PAGE_LABELS = {
    # Plugin level
    "plugin_update": _("Edit"),
    "plugin_manage": _("Manage"),
    "plugin_delete": _("Delete"),
    "plugin_restore": _("Restore"),
    "plugin_permanent_delete": _("Permanently delete"),
    "plugin_email_token_confirm": _("Confirm email"),
    "versions_bulk_delete": _("Delete versions"),
    # Tokens
    "plugin_token_list": _("Tokens"),
    "plugin_token_create": _("New token"),
    "plugin_token_detail": _("Token"),
    "plugin_token_update": _("Edit token"),
    "plugin_token_delete": _("Delete token"),
    # Version level
    "version_create": _("Add version"),
    "version_update": _("Edit version"),
    "version_manage": _("Manage version"),
    "version_delete": _("Delete version"),
    "version_feedback": _("Feedback"),
}

# URL names that are already represented by an ancestor crumb.
SELF_REFERENTIAL_PAGES = ("version_detail",)

# Token pages sit under the token list, which is not implied by the URL kwargs.
TOKEN_PAGES = (
    "plugin_token_create",
    "plugin_token_detail",
    "plugin_token_update",
    "plugin_token_delete",
)

# Tab anchors on the plugin detail page. plugin_detail.html activates the matching
# tab from the URL fragment on load, so these deep links work as-is.
VERSIONS_ANCHOR = "#plugin-versions"

# Renders nothing. Returned for every page that gets no trail.
EMPTY = {"breadcrumbs": [], "quick_links": []}


def _get_plugin(context, package_name):
    """Return the Plugin, preferring one already in context over a query."""
    for key in ("plugin", "object"):
        candidate = context.get(key)
        if isinstance(candidate, Plugin):
            return candidate
    version = context.get("version")
    if version is not None and getattr(version, "plugin_id", None):
        return version.plugin
    return Plugin.objects.filter(package_name=package_name).first()


def _quick_links(plugin, user, plugin_url):
    """Deep links into the plugin detail tabs, gated like the tabs themselves."""
    if plugin is None or user is None:
        return []

    # Mirrors the tab visibility rules in plugins/plugin_detail.html.
    is_editor = user.is_authenticated and (user.is_staff or user in plugin.editors)

    links = []
    if plugin.about:
        links.append({"title": _("About"), "url": plugin_url + "#plugin-about"})
    links.append({"title": _("Details"), "url": plugin_url + "#plugin-details"})
    links.append({"title": _("Versions"), "url": plugin_url + VERSIONS_ANCHOR})
    if is_editor:
        links.append({"title": _("Stats"), "url": plugin_url + "#plugin-stats"})
    if user.is_authenticated and (user.is_staff or user.pk == plugin.created_by_id):
        links.append(
            {
                "title": _("Tokens"),
                "url": reverse("plugin_token_list", args=[plugin.package_name]),
            }
        )
    return links


@register.inclusion_tag("plugins/includes/breadcrumbs.html", takes_context=True)
def plugin_breadcrumbs(context):
    """Build the breadcrumb trail for the current plugin page.

    The trail is rooted at the plugin itself, and only appears on pages nested
    under a plugin. It renders nothing for any page that is not scoped to a
    single plugin, and nothing on the plugin detail page - that page is the root
    of the trail, so a lone crumb naming it would add no navigation.
    """
    request = context.get("request")
    match = getattr(request, "resolver_match", None)
    if match is None:
        return EMPTY

    package_name = match.kwargs.get("package_name")
    if not package_name:
        return EMPTY

    url_name = match.url_name
    version = match.kwargs.get("version")

    if url_name == "plugin_detail":
        return EMPTY

    try:
        plugin_url = reverse("plugin_detail", args=[package_name])
    except NoReverseMatch:
        return EMPTY

    plugin = _get_plugin(context, package_name)

    crumbs = [
        {
            "title": plugin.name if plugin else package_name,
            # From a version-scoped page, going up should land on the Versions
            # tab rather than the top of the plugin page.
            "url": plugin_url + VERSIONS_ANCHOR if version else plugin_url,
        }
    ]

    if version:
        crumbs.append(
            {
                "title": version,
                "url": reverse("version_detail", args=[package_name, version]),
            }
        )

    if url_name in TOKEN_PAGES:
        crumbs.append(
            {
                "title": PLUGIN_PAGE_LABELS["plugin_token_list"],
                "url": reverse("plugin_token_list", args=[package_name]),
            }
        )

    if url_name not in SELF_REFERENTIAL_PAGES and url_name in PLUGIN_PAGE_LABELS:
        crumbs.append({"title": PLUGIN_PAGE_LABELS[url_name], "url": None})

    # The deepest crumb is the current page: drop its link.
    crumbs[-1]["url"] = None

    # Only sub-pages reach this point, and there the detail page's tab bar is out
    # of reach - hence the quick-access links.
    quick_links = _quick_links(plugin, getattr(request, "user", None), plugin_url)

    return {"breadcrumbs": crumbs, "quick_links": quick_links}
