import datetime
import json
import os.path
import xml.etree.ElementTree as ET
from datetime import timedelta

import requests
from bs4 import BeautifulSoup
from django import template
from django.conf import settings
from django.urls import reverse
from PIL import Image, UnidentifiedImageError

register = template.Library()


@register.filter("klass")
def klass(ob):
    return ob.__class__.__name__


@register.filter
def is_image_field(bound_field):
    """Return True if a bound form field wraps an ImageField."""
    return bound_field.field.__class__.__name__ == "ImageField"


@register.filter
def with_divider_flags(submenu):
    """
    Annotate each navbar submenu entry with `divider_before`: True when a
    separator is needed before it, i.e. at a boundary touching a flattened
    group (an entry with its own `submenu`). Computed once per boundary so
    two adjacent groups don't each add their own separator.
    """
    annotated = []
    prev_is_group = False
    for i, item in enumerate(submenu):
        is_group = bool(item.get("submenu"))
        item = {**item, "divider_before": i > 0 and (is_group or prev_is_group)}
        annotated.append(item)
        prev_is_group = is_group
    return annotated


@register.filter
def add_days(value, days):
    """Add days to a datetime value"""
    if value is None:
        return None
    try:
        return value + timedelta(days=int(days))
    except (ValueError, TypeError):
        return value


@register.simple_tag(takes_context=True)
def plugin_title(context):
    """Returns plugin name for title"""
    title = ""

    if "title" in context:
        title = context["title"]
    if "plugin" in context:
        title = context["plugin"].name
    if "version" in context:
        title = "{plugin} {version}".format(
            plugin=context["version"].plugin.name, version=context["version"].version
        )
    if "page_title" in context:
        title = context["page_title"]
    return title


@register.filter
def file_extension(value):
    return value.split(".")[-1].lower()


@register.filter
def is_image_valid(image):
    if not image:
        return False
    # Check if the file is an SVG by extension
    if image.path.lower().endswith(".svg"):
        return _validate_svg(image.path)
    return _validate_image(image.path)


def _validate_svg(file_path):
    try:
        # Parse the SVG file to ensure it's well-formed XML
        ET.parse(file_path)
        return True
    except (ET.ParseError, FileNotFoundError):
        return False


def _validate_image(file_path):
    try:
        img = Image.open(file_path)
        img.verify()
        return True
    except (FileNotFoundError, UnidentifiedImageError):
        return False


@register.filter
def feedbacks_not_completed(feedbacks):
    return feedbacks.filter(is_completed=False)


PLUGINS_FRESH_DAYS = getattr(settings, "PLUGINS_FRESH_DAYS", 30)


@register.filter
def is_new(plugin, days=PLUGINS_FRESH_DAYS):
    """
    A template filter to check if a plugin is new based on the created_on date.
    Default is to check if the plugin was created within the last 30 days.
    """
    if plugin.created_on:
        now = datetime.datetime.now(
            datetime.timezone.utc
        )  # Use timezone-aware datetime
        created_on = plugin.created_on

        # Ensure created_on is timezone-aware
        if created_on.tzinfo is None:
            created_on = created_on.replace(tzinfo=datetime.timezone.utc)

        delta = now - created_on
        return delta.days <= days  # Returns True if within 'days', False otherwise
    return False


# inspired by projecta <https://github.com/kartoza/prj.app>
@register.simple_tag(takes_context=True)
def version_tag(context):
    """Reads current project release from the .version file."""
    version_file = os.path.join(settings.SITE_ROOT, ".version")
    try:
        with open(version_file, "r") as file:
            version = file.read()
            context["version"] = version
    except IOError:
        context["version"] = "Unknown"
    return context["version"]


@register.simple_tag
def get_sustaining_members_section():
    """
    Get the Sustaining members HTML from the template file
    """
    template_path = os.path.join(
        settings.SITE_ROOT, "templates/flatpages/sustaining_members.html"
    )
    try:
        with open(template_path, "r") as f:
            return f.read()
    except FileNotFoundError:
        return ""


def _filter_menu(menu, user):
    """
    Filter the menu and its submenus based on user status
    """
    filtered_menu = []
    for item in menu:
        if item.get("requires_staff") and not user.is_staff:
            continue
        if item.get("requires_login") and not user.is_authenticated:
            continue
        filtered_menu.append(item)
    return filtered_menu


def _resolve_urls(menu):
    """
    Resolve each item's `url_name` (a named URL pattern) to an actual `url`
    via reverse(), recursing into nested submenus. Settings modules are
    imported before the URLconf is ready, so menu entries that need a
    reversed URL store `url_name` instead of a literal `url` and get
    resolved here, at request time, instead of being hardcoded as a path.
    """
    resolved = []
    for item in menu:
        item = dict(item)
        if "url_name" in item:
            item["url"] = reverse(item.pop("url_name"))
        if item.get("submenu"):
            item["submenu"] = _resolve_urls(item["submenu"])
        resolved.append(item)
    return resolved


@register.simple_tag()
def get_navigation_menu(user):
    """
    Get the navigation menu from the settings, filtered by user status
    """
    menu = _filter_menu(settings.NAVIGATION_MENU, user)
    return _resolve_urls(menu)


@register.simple_tag()
def get_news_menu():
    """
    Get the news menu from the settings
    """
    menu = settings.NEWS_MENU
    return menu


@register.simple_tag()
def get_top_menu():
    """
    Get the top menu from the settings
    """
    menu = settings.TOP_MENU
    return menu


@register.simple_tag()
def get_other_menu():
    """
    Get the other menu from the settings
    """
    menu = settings.OTHER_MENU
    return menu


@register.simple_tag()
def get_review_menu():
    """
    Get the review menu from the settings
    """
    menu = settings.REVIEW_MENU
    return menu


@register.simple_tag()
def get_site_url():
    """
    Get the site domain from the settings
    """
    return settings.DEFAULT_PLUGINS_SITE.rstrip("/")


@register.simple_tag()
def get_navigation_config_url():
    """
    Get the navigation config URL from the settings,
    replacing dynamic variables and saving to a new file.
    """

    # Path to the original navigation.json
    original_path = os.path.join(
        settings.SITE_ROOT, "static", "config", "navigation.json"
    )
    # Path to the new file with variables replaced
    new_path = os.path.join(
        settings.MEDIA_ROOT, "navigation_rendered.json"
    )

    # Read the original file
    with open(original_path, "r") as f:
        content = f.read()

    # Replace the variable(s)
    new_qgis_major_version = settings.NEW_QGIS_MAJOR_VERSION
    content = content.replace(
        "{{ new_qgis_major_version }}", str(new_qgis_major_version)
    )

    # Optionally validate JSON
    try:
        json.loads(content)
    except json.JSONDecodeError:
        # If the result is not valid JSON, don't save or return the new path
        return None

    # Write to the new file
    with open(new_path, "w") as f:
        f.write(content)

    # Return the URL to the new file
    return os.path.join(
        "/media", "navigation_rendered.json"
    )
