# -*- coding: utf-8 -*-
"""
Django management command to update supports_qt6 field for plugin versions
based on metadata.txt content.

This command processes all plugins in the database and updates the supports_qt6
field for their latest versions (with min_qg_version >= 3.0) by reading the
supportsQt6 field from the metadata.txt file inside the plugin package ZIP file.

Purpose:
    - Synchronize the database supports_qt6 field with the actual metadata
    - Identify plugins that are ready for QGIS 4.x (Qt6)
    - Populate the supports_qt6 field for existing plugins that may not have
      had this field set correctly during upload

Process:
    1. Iterates through all plugins in the database
    2. For each plugin, finds the latest version where min_qg_version >= 3.0
    3. Opens the plugin package ZIP file
    4. Locates and reads the metadata.txt file
    5. Parses the [general] section for the supportsQt6 field
    6. Updates the database if the value differs from what's in metadata.txt

Filtering:
    - Only processes plugin versions with min_qg_version >= 3.0
    - Skips plugins without a package file
    - Skips plugins without metadata.txt
    - Defaults to False if supportsQt6 is not specified in metadata.txt

Usage:
    # Preview changes without saving
    python manage.py update_qt6_support --dry-run --verbose

    # Update all plugins
    python manage.py update_qt6_support

    # Update all plugins with detailed output
    python manage.py update_qt6_support --verbose

    # Update a specific plugin only
    python manage.py update_qt6_support --plugin <package_name>

    # Test on a specific plugin first
    python manage.py update_qt6_support --plugin test_plugin --dry-run --verbose

Options:
    --dry-run       Show what would be updated without making changes
    --verbose       Show detailed output for each plugin processed
    --plugin NAME   Process only a specific plugin by package_name

Exit Codes:
    0: Success (all plugins processed)
    Non-zero: Errors occurred during processing (see summary)

Notes:
    - The command uses plugin_version.package.path to access the ZIP file
    - Accepts True/true/1/yes as True values for supportsQt6
    - Accepts False/false/0/no or missing field as False
    - Updates are done with update_fields=['supports_qt6'] for efficiency
    - Only the latest version per plugin (by created_on date) is processed

Author: QGIS Plugins Team
Date: November 2025
"""
import configparser
import os
import zipfile

from django.core.management.base import BaseCommand
from django.db.models import Q
from plugins.models import Plugin, PluginVersion


class Command(BaseCommand):
    help = (
        "Update supports_qt6 field for plugin versions by reading metadata.txt "
        "from plugin packages. Processes plugins with min_qg_version >= 3.0"
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            dest="dry_run",
            default=False,
            help="Show what would be updated without making changes",
        )
        parser.add_argument(
            "--verbose",
            action="store_true",
            dest="verbose",
            default=False,
            help="Show detailed output for each plugin",
        )
        parser.add_argument(
            "--plugin",
            dest="plugin_name",
            default=None,
            help="Process only a specific plugin by package_name",
        )

    def handle(self, *args, **options):
        dry_run = options.get("dry_run")
        verbose = options.get("verbose")
        plugin_name = options.get("plugin_name")

        if dry_run:
            self.stdout.write(
                self.style.WARNING("DRY RUN MODE - No changes will be saved")
            )

        # Get all plugins or a specific one
        if plugin_name:
            plugins = Plugin.objects.filter(package_name=plugin_name)
            if not plugins.exists():
                self.stdout.write(self.style.ERROR(f"Plugin '{plugin_name}' not found"))
                return
        else:
            plugins = Plugin.objects.all()

        total_plugins = plugins.count()
        self.stdout.write(f"\nProcessing {total_plugins} plugin(s)...\n")

        processed_count = 0
        updated_count = 0
        error_count = 0
        skipped_count = 0

        for plugin in plugins:
            processed_count += 1

            if verbose:
                self.stdout.write(
                    f"\n[{processed_count}/{total_plugins}] Processing: {plugin.name} ({plugin.package_name})"
                )

            # Get the latest version with min_qg_version >= 3.0
            latest_version = (
                PluginVersion.objects.filter(plugin=plugin, min_qg_version__gte="3.0")
                .order_by("-created_on")
                .first()
            )

            if not latest_version:
                if verbose:
                    self.stdout.write(
                        self.style.WARNING(
                            f"  → Skipped: No version found with min_qg_version >= 3.0"
                        )
                    )
                skipped_count += 1
                continue

            # Read metadata from the package
            try:
                supports_qt6 = self._read_supports_qt6_from_package(
                    latest_version, plugin.package_name, verbose
                )

                if supports_qt6 is None:
                    if verbose:
                        self.stdout.write(
                            self.style.WARNING(
                                f"  → Skipped: Could not read supportsQt6 from metadata.txt"
                            )
                        )
                    skipped_count += 1
                    continue

                # Check if update is needed
                if latest_version.supports_qt6 != supports_qt6:
                    if dry_run:
                        self.stdout.write(
                            self.style.WARNING(
                                f"  → Would update: {plugin.package_name} v{latest_version.version} "
                                f"supports_qt6 from {latest_version.supports_qt6} to {supports_qt6}"
                            )
                        )
                    else:
                        latest_version.supports_qt6 = supports_qt6
                        latest_version.save(update_fields=["supports_qt6"])
                        self.stdout.write(
                            self.style.SUCCESS(
                                f"  ✓ Updated: {plugin.package_name} v{latest_version.version} "
                                f"supports_qt6 set to {supports_qt6}"
                            )
                        )
                    updated_count += 1
                else:
                    if verbose:
                        self.stdout.write(
                            f"  → No change needed: supports_qt6 already {supports_qt6}"
                        )

            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(
                        f"  ✗ Error processing {plugin.package_name}: {str(e)}"
                    )
                )
                error_count += 1
                continue

        # Summary
        self.stdout.write("\n" + "=" * 60)
        self.stdout.write(self.style.SUCCESS("\nSummary:"))
        self.stdout.write(f"  Total plugins processed: {processed_count}")
        self.stdout.write(self.style.SUCCESS(f"  Updated: {updated_count}"))
        self.stdout.write(self.style.WARNING(f"  Skipped: {skipped_count}"))
        if error_count > 0:
            self.stdout.write(self.style.ERROR(f"  Errors: {error_count}"))
        self.stdout.write("=" * 60 + "\n")

    def _read_supports_qt6_from_package(self, plugin_version, package_name, verbose):
        """
        Read supportsQt6 value from metadata.txt in the plugin package.

        Returns:
            True if supportsQt6=True in metadata
            False if supportsQt6=False or not present
            None if metadata.txt cannot be read
        """
        try:
            # Check if package file exists
            if not plugin_version.package:
                if verbose:
                    self.stdout.write(self.style.WARNING("    No package file found"))
                return None

            package_path = plugin_version.package.path

            if not os.path.exists(package_path):
                if verbose:
                    self.stdout.write(
                        self.style.WARNING(
                            f"    Package file does not exist: {package_path}"
                        )
                    )
                return None

            # Open the zip file
            with zipfile.ZipFile(package_path, "r") as zip_file:
                # Look for metadata.txt
                metadata_path = None
                for file_name in zip_file.namelist():
                    if file_name.endswith("metadata.txt"):
                        metadata_path = file_name
                        break

                if not metadata_path:
                    if verbose:
                        self.stdout.write(
                            self.style.WARNING("    metadata.txt not found in package")
                        )
                    return None

                # Read and parse metadata.txt
                with zip_file.open(metadata_path) as metadata_file:
                    # Read as binary and decode
                    metadata_content = metadata_file.read().decode("utf-8")

                    # Parse with configparser
                    config = configparser.ConfigParser()
                    config.read_string(metadata_content)

                    # Check for supportsQt6 in [general] section
                    if config.has_option("general", "supportsQt6"):
                        supports_qt6_value = config.get("general", "supportsQt6")
                        # Convert to boolean
                        supports_qt6 = supports_qt6_value.strip().lower() in [
                            "true",
                            "1",
                            "yes",
                        ]

                        if verbose:
                            self.stdout.write(
                                f"    Found supportsQt6={supports_qt6_value} → {supports_qt6}"
                            )

                        return supports_qt6
                    else:
                        if verbose:
                            self.stdout.write(
                                "    supportsQt6 not found in metadata.txt"
                            )
                        return False  # Default to False if not specified

        except zipfile.BadZipFile:
            if verbose:
                self.stdout.write(self.style.ERROR("    Invalid zip file"))
            return None
        except Exception as e:
            if verbose:
                self.stdout.write(
                    self.style.ERROR(f"    Error reading package: {str(e)}")
                )
            return None
