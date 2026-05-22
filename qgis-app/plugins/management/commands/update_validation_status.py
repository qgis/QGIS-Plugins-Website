from django.core.management.base import BaseCommand
from plugins.models import (
    VALIDATION_STATUS_BLOCKED,
    VALIDATION_STATUS_VALIDATED,
    PluginVersion,
)


class Command(BaseCommand):
    help = (
        "Update validation_status on PluginVersion instances based on existing "
        "security scan results, without re-running any scans."
    )

    def handle(self, *args, **options):
        versions = PluginVersion.objects.select_related("security_scan").filter(
            validation_status__in=["pending", "validating"]
        )

        updated = 0
        skipped = 0

        for version in versions.iterator():
            if not hasattr(version, "security_scan"):
                skipped += 1
                continue

            scan = version.security_scan
            new_status = (
                VALIDATION_STATUS_BLOCKED
                if scan.critical_count > 0
                else VALIDATION_STATUS_VALIDATED
            )

            PluginVersion.objects.filter(pk=version.pk).update(
                validation_status=new_status
            )
            self.stdout.write(
                f"  {version.plugin.package_name} v{version.version}: "
                f"{version.validation_status} → {new_status}"
            )
            updated += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"\nDone. Updated: {updated}, Skipped (no scan): {skipped}."
            )
        )
