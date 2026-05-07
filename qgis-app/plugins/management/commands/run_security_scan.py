from django.core.management.base import BaseCommand

from plugins.models import Plugin
from plugins.security_utils import run_security_scan


class Command(BaseCommand):
    help = (
        "Run security scan on the latest version of each plugin "
        "if a scan result does not already exist."
    )

    def handle(self, *args, **options):
        plugins = Plugin.objects.all()
        scanned = 0
        skipped = 0
        failed = 0

        for plugin in plugins.iterator():
            latest_version = (
                plugin.pluginversion_set.order_by("-created_on").first()
            )

            if latest_version is None:
                self.stdout.write(
                    self.style.WARNING(
                        f"  {plugin.package_name}: no approved version, skipping."
                    )
                )
                skipped += 1
                continue

            if hasattr(latest_version, "security_scan"):
                self.stdout.write(
                    f"  {plugin.package_name} v{latest_version.version}: "
                    "already scanned, skipping."
                )
                skipped += 1
                continue

            self.stdout.write(
                f"  Scanning {plugin.package_name} v{latest_version.version} ..."
            )
            result = run_security_scan(latest_version)

            if result is not None:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"  {plugin.package_name} v{latest_version.version}: "
                        f"scan complete (status: {result.overall_status})."
                    )
                )
                scanned += 1
            else:
                self.stdout.write(
                    self.style.ERROR(
                        f"  {plugin.package_name} v{latest_version.version}: "
                        "scan failed."
                    )
                )
                failed += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"\nDone. Scanned: {scanned}, Skipped: {skipped}, Failed: {failed}."
            )
        )
