"""
Staggered annual email re-verification.

``send_anniversary_reverifications`` runs daily and picks the email addresses
whose *first confirmation was sent* exactly one year ago today, then re-runs the
email confirmation for each — even for addresses already confirmed — to prove
the contact email is still live a year later. Past confirmation records are kept
as history; a fresh pending record is created via
``PluginEmailConfirmation.force_new_for_email``.

Keying off the first ``sent_at`` (rather than the plugin's first-publish date)
guarantees we never re-verify an address before a full year has elapsed since it
was first asked to confirm.

This is additive to the monthly ``send_pending_email_confirmations`` sweep,
which keeps chasing the unconfirmed population.
"""

from collections import defaultdict

from celery import shared_task
from celery.utils.log import get_task_logger
from django.db.models import Min
from django.utils.timezone import now
from plugins.email_utils import send_confirmation_email
from plugins.models import Plugin, PluginEmailConfirmation, PluginEmailConfirmationError

logger = get_task_logger(__name__)


@shared_task
def send_anniversary_reverifications() -> dict:
    """
    Re-verify every email address whose first confirmation was sent exactly one
    year ago today, regardless of current confirmation state.

    Returns a stats dict ``{sent, skipped, errors}``.
    """
    today = now().date()

    # Earliest confirmation ever sent per address.
    first_sent = (
        PluginEmailConfirmation.objects.values("email")
        .annotate(first_sent_at=Min("sent_at"))
        .filter(
            first_sent_at__month=today.month,
            first_sent_at__day=today.day,
        )
    )

    # Feb 29 first-sends re-verify on Feb 28 in non-leap years so they aren't
    # skipped for three out of every four years.
    is_leap = today.year % 4 == 0 and (today.year % 100 != 0 or today.year % 400 == 0)
    if today.month == 2 and today.day == 28 and not is_leap:
        first_sent = (
            PluginEmailConfirmation.objects.values("email")
            .annotate(first_sent_at=Min("sent_at"))
            .filter(first_sent_at__month=2, first_sent_at__day=29)
        )

    # Only addresses whose first send is at least a year old qualify — guards
    # against re-verifying an address first contacted earlier today.
    due_emails = [
        row["email"] for row in first_sent if row["first_sent_at"].year < today.year
    ]
    if not due_emails:
        logger.info("send_anniversary_reverifications: no addresses due today")
        return {"sent": 0, "skipped": 0, "errors": 0}

    # Map each due address to its still-current plugins (email may have changed
    # since the first round; force_new_for_email re-checks the match too).
    email_to_plugins = defaultdict(list)
    for plugin in Plugin.approved_objects.filter(
        is_deleted=False, email__in=due_emails
    ).iterator():
        email_to_plugins[plugin.email].append(plugin)

    sent = skipped = errors = 0

    for email in due_emails:
        plugins = email_to_plugins.get(email)
        if not plugins:
            skipped += 1
            continue

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

        # Retire the previous confirmation: a new yearly round means the address
        # must prove itself again, so existing confirmations stop counting (kept
        # as history) until the fresh link is clicked. The just-created pending
        # record is unconfirmed, so it is unaffected.
        PluginEmailConfirmation.objects.filter(
            email=email,
            confirmed_at__isnull=False,
            superseded_at__isnull=True,
        ).update(superseded_at=now())

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
