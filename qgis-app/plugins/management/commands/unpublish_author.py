"""
Unpublish every approved plugin version that belongs to one author.

A version belongs to the author when they uploaded it, or when they created
the plugin it belongs to. Unpublishing sets ``approved`` to False, the same as
the Unapprove button on the version page. The package files stay in place and
nobody gets an email.

The command prints the ID of every version it touches. Keep that output if
you might need to publish the versions again.

Usage examples:
  # List the versions that would be unpublished, without changing anything
  python manage.py unpublish_author jdoe --dry-run

  # Unpublish them
  python manage.py unpublish_author jdoe
"""

from typing import Any

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db.models import Q
from plugins.models import PluginVersion


class Command(BaseCommand):
    help = "Unpublish every approved plugin version from one author."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("username", help="The author's username.")
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="List the versions without unpublishing them.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        username = options["username"]
        try:
            author = User.objects.get(username=username)
        except User.DoesNotExist:
            raise CommandError(f'We could not find a user called "{username}".')

        versions = list(
            PluginVersion.objects.filter(
                Q(created_by=author) | Q(plugin__created_by=author),
                approved=True,
            ).select_related("plugin")
        )
        if not versions:
            self.stdout.write(f"{username} has no published versions.")
            return

        for version in versions:
            self.stdout.write(
                f"  {version.pk}\t{version.plugin.package_name}\t{version.version}"
            )

        count = f"{len(versions)} version{'' if len(versions) == 1 else 's'}"
        if options["dry_run"]:
            self.stdout.write(f"\nDry run: {count} would be unpublished.")
            return

        for version in versions:
            version.approved = False
            version.save()
        self.stdout.write(self.style.SUCCESS(f"\nUnpublished {count} from {username}."))
