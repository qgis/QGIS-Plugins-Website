"""
Celery tasks for automatic email confirmation triggering.

``check_and_send_confirmation`` — fired on plugin approval or email change;
  sends a confirmation email if the plugin's current email is not yet confirmed.

``send_pending_email_confirmations`` — periodic sweep that cleans up expired
  pending tokens and sends fresh confirmations to all approved plugins whose
  email is still unconfirmed.
"""

from collections import defaultdict

from celery import shared_task
from celery.utils.log import get_task_logger
from django.utils.timezone import now
from plugins.email_utils import send_confirmation_email
from plugins.models import Plugin, PluginEmailConfirmation, PluginEmailConfirmationError

logger = get_task_logger(__name__)


@shared_task
def check_and_send_confirmation(plugin_pk):
    """
    Send an email confirmation for *plugin_pk* if its current email address
    has not yet been confirmed.

    Safe to call repeatedly — :meth:`PluginEmailConfirmation.create_for_email`
    is idempotent: it skips already-confirmed addresses and reuses existing
    pending confirmations without resending.
    """
    try:
        plugin = (
            Plugin.objects.select_related("created_by")
            .prefetch_related("owners")
            .get(pk=plugin_pk)
        )
    except Plugin.DoesNotExist:
        logger.warning("check_and_send_confirmation: plugin pk=%s not found", plugin_pk)
        return

    if not plugin.email:
        return

    if not Plugin.approved_objects.filter(pk=plugin_pk, is_deleted=False).exists():
        return

    try:
        confirmation, created = PluginEmailConfirmation.create_for_email(
            plugin.email, [plugin]
        )
        if created:
            send_confirmation_email(confirmation)
            logger.info(
                "Sent confirmation email for plugin %s to <%s>",
                plugin.package_name,
                plugin.email,
            )
        else:
            logger.debug(
                "Skipped confirmation for plugin %s (already confirmed or pending)",
                plugin.package_name,
            )
    except Exception:
        logger.exception(
            "check_and_send_confirmation failed for plugin pk=%s", plugin_pk
        )


@shared_task
def send_pending_email_confirmations():
    """
    Periodic sweep: expire stale pending tokens, then send fresh confirmations
    to every approved, non-deleted plugin whose email is still unconfirmed.

    Unlike ``--resend``, this does **not** touch confirmed records — it only
    cleans up tokens whose window has passed so those plugins get a new link.

    Returns a stats dict ``{sent, skipped, errors}`` for logging.
    """
    # Delete expired *pending* confirmations so plugins get a fresh token.
    expired = PluginEmailConfirmation.objects.filter(
        confirmed_at__isnull=True,
        expires_at__lt=now(),
    )
    expired_count = expired.count()
    expired.delete()
    if expired_count:
        logger.info("Deleted %d expired pending confirmation(s)", expired_count)

    # Group all active plugins by email address.
    qs = Plugin.approved_objects.filter(is_deleted=False).exclude(email="")
    email_to_plugins = defaultdict(list)
    for plugin in qs.iterator():
        email_to_plugins[plugin.email].append(plugin)

    sent = skipped = errors = 0

    for email, plugins in email_to_plugins.items():
        confirmation, created = PluginEmailConfirmation.create_for_email(email, plugins)

        if not created:
            skipped += 1
            continue

        try:
            send_confirmation_email(confirmation)
            logger.info(
                "Periodic: sent confirmation to <%s> (%d plugin(s))",
                email,
                len(plugins),
            )
            sent += 1
        except Exception as exc:
            logger.exception("Periodic: failed to send to <%s>: %s", email, exc)
            PluginEmailConfirmationError.objects.create(
                email=email,
                plugins=", ".join(p.package_name for p in plugins),
                error=str(exc),
            )
            errors += 1

    logger.info(
        "send_pending_email_confirmations done — sent=%d skipped=%d errors=%d",
        sent,
        skipped,
        errors,
    )
    return {"sent": sent, "skipped": skipped, "errors": errors}
