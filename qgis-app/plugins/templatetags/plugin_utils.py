from django import template
from PIL import Image, UnidentifiedImageError
import xml.etree.ElementTree as ET
import os.path
from django.conf import settings
from bs4 import BeautifulSoup
import requests
import datetime

register = template.Library()


@register.filter("klass")
def klass(ob):
    return ob.__class__.__name__


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
    return value.split('.')[-1].lower()

@register.filter
def is_image_valid(image):
    if not image:
        return False
    # Check if the file is an SVG by extension
    if image.path.lower().endswith('.svg'):
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
        now = datetime.datetime.now(datetime.timezone.utc)  # Use timezone-aware datetime
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
    template_path = os.path.join(settings.SITE_ROOT, 'templates/flatpages/sustaining_members.html')
    try:
        with open(template_path, 'r') as f:
            return f.read()
    except FileNotFoundError:
        return ""

def _filter_menu(menu, user):
    """
    Filter the menu and its submenus based on user status
    """
    filtered_menu = []
    for item in menu:
        if item.get('requires_staff') and not user.is_staff:
            continue
        if item.get('requires_login') and not user.is_authenticated:
            continue
        filtered_menu.append(item)
    return filtered_menu

@register.simple_tag()
def get_navigation_menu(user):
    """
    Get the navigation menu from the settings, filtered by user status
    """
    menu = _filter_menu(settings.NAVIGATION_MENU, user)
    return menu