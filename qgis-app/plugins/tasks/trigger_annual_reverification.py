"""
Staggered annual email re-verification.

``send_anniversary_reverifications`` runs daily and picks the plugins whose
first-publish anniversary is today, then *fully re-runs* the email confirmation
for each — even for addresses already confirmed — to prove the contact email is
still live a year later. Past confirmation records are kept as history; a fresh
pending record is created via ``PluginEmailConfirmation.force_new_for_email``.

This is additive to the monthly ``send_pending_email_confirmations`` sweep,
which keeps chasing the unconfirmed population.
"""

from collections import defaultdict

from celery import shared_task
from celery.utils.log import get_task_logger
from django.db.models import Min, Q
from django.utils.timezone import now
from plugins.email_utils import send_confirmation_email
from plugins.models import Plugin, PluginEmailConfirmation, PluginEmailConfirmationError

logger = get_task_logger(__name__)


@shared_task
def send_anniversary_reverifications() -> dict:
    """
    Re-verify the contact email of every approved plugin whose first-published
    anniversary is today, regardless of current confirmation state.

    Returns a stats dict ``{sent, skipped, errors}``.
    """
    today = now().date()

    qs = (
        Plugin.approved_objects.filter(is_deleted=False)
        .exclude(email="")
        .annotate(
            first_pub=Min(
                "pluginversion__created_on",
                filter=Q(pluginversion__approved=True),
            )
        )
        .filter(first_pub__month=today.month, first_pub__day=today.day)
    )

    # Feb 29 plugins re-verify on Feb 28 in non-leap years so they aren't skipped.
    is_leap = today.year % 4 == 0 and (today.year % 100 != 0 or today.year % 400 == 0)
    if today.month == 2 and today.day == 28 and not is_leap:
        qs = (
            Plugin.approved_objects.filter(is_deleted=False)
            .exclude(email="")
            .annotate(
                first_pub=Min(
                    "pluginversion__created_on",
                    filter=Q(pluginversion__approved=True),
                )
            )
            .filter(
                Q(first_pub__month=2, first_pub__day=28)
                | Q(first_pub__month=2, first_pub__day=29)
            )
        )

    email_to_plugins = defaultdict(list)
    for plugin in qs.iterator():
        email_to_plugins[plugin.email].append(plugin)

    sent = skipped = errors = 0

    for email, plugins in email_to_plugins.items():
        # Guard against double-runs in the same day: skip if a pending record
        # for this email was already created today.
        if PluginEmailConfirmation.objects.filter(
            email=email,
            confirmed_at__isnull=True,
            sent_at__date=today,
        ).exists():
            skipped += 1
            continue

        confirmation = PluginEmailConfirmation.force_new_for_email(email, plugins)
        if confirmation is None:
            skipped += 1
            continue

        try:
            send_confirmation_email(confirmation)
            logger.info(
                f"Anniversary: re-verification sent to <{email}> "
                f"({len(plugins)} plugin(s))"
            )
            sent += 1
        except Exception as exc:
            logger.exception(f"Anniversary: failed to send to <{email}>: {exc}")
            PluginEmailConfirmationError.objects.create(
                email=email,
                plugins=", ".join(p.package_name for p in plugins),
                error=str(exc),
            )
            errors += 1

    logger.info(
        f"send_anniversary_reverifications done — "
        f"sent={sent} skipped={skipped} errors={errors}"
    )
    return {"sent": sent, "skipped": skipped, "errors": errors}
