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
def check_and_send_confirmation(plugin_pk: int) -> None:
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
        logger.warning(f"check_and_send_confirmation: plugin pk={plugin_pk} not found")
        return

    if not plugin.email:
        logger.info(
            f"check_and_send_confirmation: plugin pk={plugin_pk} has no email — skipping"
        )
        return

    logger.info(
        f"check_and_send_confirmation: checking plugin pk={plugin_pk} "
        f"({plugin.package_name}) with email <{plugin.email}>"
    )

    # Send once the plugin is reachable for approval: it is non-deleted and
    # either already approved or has at least one validated (available) version.
    # This lets the confirmation go out before manual approval, which is gated
    # on the email being confirmed.
    if plugin.is_deleted:
        logger.info(
            f"check_and_send_confirmation: plugin pk={plugin_pk} is deleted — skipping"
        )
        return
    if not plugin.approved and not any(
        v.is_available for v in plugin.pluginversion_set.all()
    ):
        logger.info(
            f"check_and_send_confirmation: plugin pk={plugin_pk} ({plugin.package_name}) "
            f"has no available version and is not approved — likely still validating or "
            f"blocked by the security scan; skipping"
        )
        return

    try:
        confirmation, created = PluginEmailConfirmation.create_for_email(
            plugin.email, [plugin]
        )
        if created:
            send_confirmation_email(confirmation)
            logger.info(
                f"Sent confirmation email for plugin {plugin.package_name} to <{plugin.email}>"
            )
        elif confirmation is None:
            logger.info(
                f"check_and_send_confirmation: email <{plugin.email}> is already confirmed "
                f"for plugin {plugin.package_name} — no new confirmation needed"
            )
        else:
            logger.info(
                f"check_and_send_confirmation: reusing existing pending confirmation for "
                f"<{plugin.email}> (plugin {plugin.package_name}) — not resending"
            )
    except Exception:
        logger.exception(
            f"check_and_send_confirmation failed for plugin pk={plugin_pk}"
        )


@shared_task
def send_pending_email_confirmations() -> dict:
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
        logger.info(f"Deleted {expired_count} expired pending confirmation(s)")

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
                f"Periodic: sent confirmation to <{email}> ({len(plugins)} plugin(s))"
            )
            sent += 1
        except Exception as exc:
            logger.exception(f"Periodic: failed to send to <{email}>: {exc}")
            PluginEmailConfirmationError.objects.create(
                email=email,
                plugins=", ".join(p.package_name for p in plugins),
                error=str(exc),
            )
            errors += 1

    logger.info(
        f"send_pending_email_confirmations done — sent={sent} skipped={skipped} errors={errors}"
    )
    return {"sent": sent, "skipped": skipped, "errors": errors}
