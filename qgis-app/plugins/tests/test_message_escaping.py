"""
Tests for HTML escaping of flash messages and form errors.

base.html used to render every message through |safe, so any message built
from uploader supplied data (plugin name, archive folder names, metadata read
out of the package) was an injection point. Messages that genuinely need
markup now mark themselves safe at the call site instead.
"""

from django.contrib import messages
from django.forms import ValidationError
from django.shortcuts import render
from django.test import TestCase, override_settings
from django.urls import include, path
from django.utils.safestring import mark_safe
from plugins import forms as plugin_forms

HOSTILE = '<img src=x onerror="alert(1)">'


def hostile_message_view(request):
    messages.warning(request, HOSTILE)
    return render(request, "base.html", {})


def safe_markup_view(request):
    messages.warning(request, mark_safe("<strong>emphasis</strong>"))
    return render(request, "base.html", {})


urlpatterns = [
    path("hostile/", hostile_message_view),
    path("markup/", safe_markup_view),
    # base.html reverses site URLs, so the real urlconf has to stay reachable.
    path("", include("urls")),
]


@override_settings(ROOT_URLCONF=__name__)
class FlashMessageEscapingTest(TestCase):
    def test_plain_message_is_escaped(self):
        response = self.client.get("/hostile/")
        self.assertNotContains(response, HOSTILE)
        self.assertContains(response, "&lt;img src=x onerror=&quot;alert(1)&quot;&gt;")

    def test_message_marked_safe_still_renders_markup(self):
        """Removing |safe must not flatten the messages that need markup."""
        response = self.client.get("/markup/")
        self.assertContains(response, "<strong>emphasis</strong>", html=False)


class ValidatorErrorEscapingTest(TestCase):
    """The package validator quotes metadata straight out of the archive."""

    def _raise_hostile(self, *args, **kwargs):
        raise ValidationError([HOSTILE])

    def test_clean_package_escapes_validator_messages(self):
        self.addCleanup(setattr, plugin_forms, "validator", plugin_forms.validator)
        plugin_forms.validator = self._raise_hostile

        form = plugin_forms.PackageUploadForm()
        form.cleaned_data = {"package": object()}
        with self.assertRaises(ValidationError) as raised:
            form.clean_package()

        rendered = str(raised.exception.messages[0])
        self.assertNotIn(HOSTILE, rendered)
        self.assertIn("&lt;img", rendered)
