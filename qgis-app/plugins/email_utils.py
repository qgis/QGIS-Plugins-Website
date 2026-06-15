# -*- coding: utf-8 -*-
"""
Email helpers for plugin email confirmation.

Extracted from views.py so they can be imported by both views and Celery tasks
without creating circular imports (views already imports from tasks).
"""

import datetime
import logging
from collections import defaultdict

from django.conf import settings
from django.contrib.sites.models import Site
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils import timezone


def _format_expiry(value):
    """
    Format a confirmation-expiry datetime in UTC with an explicit zone label.

    The project runs with ``USE_TZ = False`` and stores naive datetimes in the
    configured ``TIME_ZONE``; ``strftime("%Z")`` is blank for naive values.  We
    make the value aware, then convert to UTC so plugin authors worldwide see a
    single unambiguous reference (e.g. "2026-07-10 07:46 UTC").
    """
    if timezone.is_naive(value):
        value = timezone.make_aware(value)
    return value.astimezone(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M %Z")


def send_confirmation_email(confirmation):
    """
    Send one HTML+plaintext confirmation email for a PluginEmailConfirmation.
    Builds the plugin list from the M2M relation.
    """
    domain = Site.objects.get_current().domain
    confirmation_url = f"https://{domain}/plugins/confirm-email/{confirmation.key}/"
    expires_at = _format_expiry(confirmation.expires_at)
    plugins = list(confirmation.plugins.all())
    plugin_list = [
        {"name": p.name, "url": f"https://{domain}{p.get_absolute_url()}"}
        for p in plugins
    ]
    context = {
        "email": confirmation.email,
        "plugins": plugin_list,
        "confirmation_url": confirmation_url,
        "expires_at": expires_at,
        "token": confirmation.key,
        "site_domain": domain,
    }

    if len(plugins) == 1:
        subject = f"[QGIS Plugins] Please confirm your email for: {plugins[0].name}"
    else:
        subject = (
            f"[QGIS Plugins] Please confirm your email address ({len(plugins)} plugins)"
        )

    text_body = render_to_string("plugins/email_confirmation.txt", context)
    html_body = render_to_string("plugins/email_confirmation.html", context)

    recipients = confirmation.email
    if settings.DEBUG:
        if not settings.DEVELOPER_EMAILS:
            return
        recipients = settings.DEVELOPER_EMAILS

    msg = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=recipients.split(
            ","
        ),  # There are some cases where a plugin's email contains multiple comma-separated emails
    )
    msg.attach_alternative(html_body, "text/html")
    msg.send()

    # Tokenless heads-up to the responsible account holders so that a shared or
    # unmonitored contact mailbox does not silently stall confirmation.  A
    # failure here must never affect the primary confirmation email above (and
    # must not propagate to callers, which record PluginEmailConfirmationError).
    try:
        notify_editors_of_pending_confirmation(confirmation)
    except Exception:
        logging.exception(
            "Failed to notify editors of pending confirmation for %s",
            confirmation.email,
        )


def notify_editors_of_pending_confirmation(confirmation):
    """
    Send a tokenless heads-up to the account holders responsible for the
    plugins in *confirmation* (``plugin.editors`` — owners + creator).

    The metadata ``email`` may be a shared organisation mailbox that nobody
    monitors; this alerts the real, logged-in editors that a confirmation is
    pending so a human can act on it.  It deliberately carries **no token and
    no direct confirmation link** — possession of the token remains the only
    proof of mailbox control — and points editors to the login-gated "Email
    confirmation pending" button instead.

    One personalised email is sent per editor, scoped to only the plugins that
    editor actually manages: a single shared address can cover plugins with
    different editor sets, and the token-entry page is gated on ``editors``.
    """
    domain = Site.objects.get_current().domain
    expires_at = _format_expiry(confirmation.expires_at)

    if settings.DEBUG and not settings.DEVELOPER_EMAILS:
        return

    # Addresses that already received the token email — don't ping them again.
    confirmed_addresses = {
        part.strip().lower() for part in confirmation.email.split(",") if part.strip()
    }

    # Build editor -> [plugins in this confirmation they can edit].  set() dedupes
    # editors per plugin (created_by may also be an owner); each plugin is visited
    # once, so an editor accumulates only the distinct plugins they manage.
    editor_plugins = defaultdict(list)
    for plugin in confirmation.plugins.all():
        for editor in set(plugin.editors):
            editor_plugins[editor].append(plugin)

    for editor, plugins in editor_plugins.items():
        email = (editor.email or "").strip()
        if not email or email.lower() in confirmed_addresses:
            continue

        plugin_list = [
            {
                "name": p.name,
                "url": f"https://{domain}{p.get_absolute_url()}",
                "confirm_url": (
                    f"https://{domain}/plugins/{p.package_name}/confirm-email-token/"
                ),
            }
            for p in plugins
        ]
        context = {
            "email": confirmation.email,
            "plugins": plugin_list,
            "expires_at": expires_at,
            "site_domain": domain,
        }

        if len(plugins) == 1:
            subject = (
                "[QGIS Plugins] Action may be needed: email confirmation pending "
                f"for {plugins[0].name}"
            )
        else:
            subject = (
                "[QGIS Plugins] Action may be needed: email confirmation pending "
                f"for {len(plugins)} plugins you manage"
            )

        text_body = render_to_string("plugins/email_editor_notification.txt", context)
        html_body = render_to_string("plugins/email_editor_notification.html", context)

        recipients = [email]
        if settings.DEBUG:
            recipients = [
                part.strip()
                for part in settings.DEVELOPER_EMAILS.split(",")
                if part.strip()
            ]

        try:
            msg = EmailMultiAlternatives(
                subject=subject,
                body=text_body,
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=recipients,
            )
            msg.attach_alternative(html_body, "text/html")
            msg.send()
        except Exception:
            logging.exception(
                "Failed to send editor confirmation notification to %s", email
            )
