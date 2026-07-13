"""
Celery task to send a superuser-composed news/communication email to every
confirmed plugin contact address plus the account emails of those plugins'
collaborators.  Recipients are sent as BCC in batches (many SMTP providers cap
the number of BCC recipients per message, e.g. 50), reusing a single SMTP
connection for the whole run.
"""

from celery import shared_task
from celery.utils.log import get_task_logger
from django.conf import settings
from django.core.mail import EmailMessage, get_connection
from django.utils import timezone
from plugins.models import Plugin, PluginEmailCommunication, PluginEmailConfirmation

logger = get_task_logger(__name__)

# Fallback BCC recipients per message when EMAIL_COMMUNICATION_BATCH_SIZE is
# unset.  Kept conservative to satisfy the common provider cap of 50.
DEFAULT_BATCH_SIZE = 50


def _chunked(seq, size):
    """Yield successive ``size``-length slices of ``seq``."""
    for start in range(0, len(seq), size):
        yield seq[start : start + size]


def get_communication_recipients() -> list:
    """
    Build the deduped recipient list for an email communication.

    Includes, for every still-active (approved, non-deleted) plugin whose
    *current* contact address has been confirmed:
      * that confirmed contact address (split on "," — the field may hold
        several), and
      * the account emails of the plugin's collaborators (owners + creator,
        i.e. ``plugin.editors``).

    Returns original-cased addresses, deduplicated case-insensitively.
    """
    seen = set()  # lowercased addresses already added
    recipients = []

    def add(addr):
        addr = (addr or "").strip()
        if not addr:
            return
        key = addr.lower()
        if key in seen:
            return
        seen.add(key)
        recipients.append(addr)

    # Confirmation is tracked per email address: an address is eligible if any
    # plugin has confirmed it, so collect the full set of confirmed addresses.
    confirmed_emails = set(
        PluginEmailConfirmation.objects.filter(
            confirmed_at__isnull=False,
            superseded_at__isnull=True,
        ).values_list("email", flat=True)
    )

    plugins = (
        Plugin.approved_objects.filter(is_deleted=False)
        .exclude(email="")
        .select_related("created_by")
        .prefetch_related("owners")
    )

    for plugin in plugins:
        # Only target the plugin's *current* address, and only if that address
        # has been confirmed by any plugin sharing it.
        if plugin.email not in confirmed_emails:
            continue
        for part in plugin.email.split(","):
            add(part)
        for editor in plugin.editors:
            if editor is not None:
                add(editor.email)

    return recipients


@shared_task
def send_email_communication(communication_pk):
    """
    Send the :class:`PluginEmailCommunication` identified by *communication_pk*
    to all confirmed contacts and collaborators, BCC, in batches.
    """
    try:
        comm = PluginEmailCommunication.objects.get(pk=communication_pk)
    except PluginEmailCommunication.DoesNotExist:
        logger.error("send_email_communication: no record pk=%s", communication_pk)
        return {"recipients": 0, "messages": 0, "error": "missing record"}

    try:
        recipients = get_communication_recipients()

        # In development, never email real authors — redirect to the developers.
        if settings.DEBUG:
            recipients = (
                [a.strip() for a in settings.DEVELOPER_EMAILS.split(",") if a.strip()]
                if settings.DEVELOPER_EMAILS
                else []
            )

        # Plain-text emails (no HTML) with recipients in BCC, split into batches
        # so we stay under the provider's per-message recipient cap.  Providers
        # count *total* recipients (To + Cc + Bcc), so the To address consumes
        # one slot of the cap — reserve room for it, or the batch overflows by
        # one and the send is rejected (SMTP 550, "recipients cannot exceed N").
        to_list = [settings.DEFAULT_FROM_EMAIL]
        cap = (
            getattr(settings, "EMAIL_COMMUNICATION_BATCH_SIZE", DEFAULT_BATCH_SIZE)
            or DEFAULT_BATCH_SIZE
        )
        bcc_per_message = max(1, cap - len(to_list))
        sent_messages = 0
        if recipients:
            connection = get_connection()
            connection.open()
            try:
                for batch in _chunked(recipients, bcc_per_message):
                    email = EmailMessage(
                        subject=comm.subject,
                        body=comm.body,
                        from_email=settings.DEFAULT_FROM_EMAIL,
                        to=to_list,
                        bcc=batch,
                        connection=connection,
                    )
                    email.send()
                    sent_messages += 1
            finally:
                connection.close()

        comm.recipient_count = len(recipients)
        comm.sent_at = timezone.now()
        comm.status = PluginEmailCommunication.STATUS_SENT
        comm.save(update_fields=["recipient_count", "sent_at", "status"])
        logger.info(
            "Sent communication '%s' to %s recipient(s)",
            comm.subject,
            len(recipients),
        )
        return {"recipients": len(recipients), "messages": sent_messages}
    except Exception as exc:
        comm.status = PluginEmailCommunication.STATUS_FAILED
        comm.error = str(exc)
        comm.save(update_fields=["status", "error"])
        logger.exception("Failed to send communication pk=%s", communication_pk)
        raise
