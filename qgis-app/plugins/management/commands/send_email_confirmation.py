# -*- coding: utf-8 -*-
"""
Management command to send email confirmation requests to plugin authors.

One email is sent per *unique email address*, covering every plugin that uses
that address.  A single click in the email confirms the address for all of
those plugins simultaneously.

Usage examples:
  # Send to all plugins with an unconfirmed / unconfirmed email (skips already confirmed)
  python manage.py send_email_confirmation

  # Send to a specific email address (covers all plugins sharing that address)
  python manage.py send_email_confirmation --email author@example.com

  # Force resend even if already confirmed or a pending request exists
  python manage.py send_email_confirmation --resend

  # Dry run: print what would be sent without actually sending anything
  python manage.py send_email_confirmation --dry-run
"""

from collections import defaultdict

from django.core.management.base import BaseCommand
from plugins.email_utils import send_confirmation_email
from plugins.models import Plugin, PluginEmailConfirmation, PluginEmailConfirmationError


class Command(BaseCommand):
    help = "Send email confirmation requests to plugin author email addresses."

    def add_arguments(self, parser):
        parser.add_argument(
            "--email",
            metavar="EMAIL_ADDRESS",
            help="Send only to plugins registered under this email address.",
        )
        parser.add_argument(
            "--resend",
            action="store_true",
            default=False,
            help=(
                "Force a new confirmation email even when a valid pending "
                "request already exists or the email was already confirmed."
            ),
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Print what would happen without actually sending emails.",
        )

    def handle(self, *args, **options):
        email_filter = options["email"]
        resend = options["resend"]
        dry_run = options["dry_run"]

        qs = Plugin.approved_objects.filter(is_deleted=False).exclude(email="")
        if email_filter:
            qs = qs.filter(email=email_filter)
            if not qs.exists():
                self.stderr.write(
                    self.style.ERROR(
                        f"No active plugins found with email='{email_filter}'"
                    )
                )
                return
            self.stdout.write(
                f"  --email '{email_filter}': found {qs.count()} plugin(s)."
            )

        # Group plugins by their email address.
        email_to_plugins = defaultdict(list)
        for plugin in qs.iterator():
            email_to_plugins[plugin.email].append(plugin)

        sent = skipped = errors = 0

        for email, plugins in sorted(email_to_plugins.items()):
            plugin_names = ", ".join(p.package_name for p in plugins)

            if dry_run:
                self.stdout.write(
                    f"  DRY-RUN  Would send to <{email}> "
                    f"({len(plugins)} plugin(s): {plugin_names})"
                )
                sent += 1
                continue

            if resend:
                # Delete any existing pending confirmations for this email so
                # create_for_email always builds a fresh one.
                PluginEmailConfirmation.objects.filter(
                    email=email,
                    confirmed_at__isnull=True,
                    plugins__in=plugins,
                ).delete()
                # Also clear confirmed records when --resend forces re-verification.
                PluginEmailConfirmation.objects.filter(
                    email=email,
                    confirmed_at__isnull=False,
                    plugins__in=plugins,
                ).delete()

            confirmation, created = PluginEmailConfirmation.create_for_email(
                email, plugins
            )

            if confirmation is None:
                # All plugins already confirmed for this address.
                self.stdout.write(
                    f"  SKIP  <{email}> — all {len(plugins)} plugin(s) already confirmed"
                )
                skipped += 1
                continue

            if not created:
                # A valid pending confirmation already exists.
                self.stdout.write(
                    f"  SKIP  <{email}> — pending confirmation already exists "
                    f"({len(plugins)} plugin(s))"
                )
                skipped += 1
                continue

            try:
                send_confirmation_email(confirmation)
                self.stdout.write(
                    self.style.SUCCESS(
                        f"  SENT  <{email}> — {len(plugins)} plugin(s): {plugin_names}"
                    )
                )
                sent += 1
            except Exception as exc:
                self.stderr.write(self.style.ERROR(f"  ERROR  <{email}>: {exc}"))
                PluginEmailConfirmationError.objects.create(
                    email=email,
                    plugins=plugin_names,
                    error=str(exc),
                )
                errors += 1

        summary = f"\nDone. Sent: {sent}  Skipped: {skipped}  Errors: {errors}"
        if dry_run:
            summary = f"\nDry run. Would send: {sent}"
        self.stdout.write(self.style.SUCCESS(summary))
        if errors:
            self.stdout.write(
                self.style.WARNING(
                    f"  {errors} error(s) saved to the Plugin Email Confirmation Errors table."
                )
            )
