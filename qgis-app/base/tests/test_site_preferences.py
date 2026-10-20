from base.models.site_preferences import SitePreference
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class SitePreferenceMigrationTests(TransactionTestCase):
    def test_upgrade_preserves_existing_preferences_and_supports_version_storage(self):
        previous = [("preferences", "0002_auto_20181220_0803")]
        current = [("preferences", "0003_sitepreference")]
        executor = MigrationExecutor(connection)
        executor.migrate(previous)
        try:
            apps = executor.loader.project_state(previous).apps
            preferences = apps.get_model("preferences", "Preferences").objects.create()
            site = apps.get_model("sites", "Site").objects.create(
                domain="preferences-test.example", name="Preferences test"
            )
            preferences.sites.add(site)
        finally:
            MigrationExecutor(connection).migrate(current)

        apps = MigrationExecutor(connection).loader.project_state(current).apps
        migrated = apps.get_model("preferences", "Preferences").objects.get(
            pk=preferences.pk
        )
        self.assertEqual(list(migrated.sites.values_list("pk", flat=True)), [site.pk])
        saved = SitePreference.objects.create(qgis_versions="3.44,3.40")
        self.assertEqual(
            SitePreference.objects.get(pk=saved.pk).qgis_versions, "3.44,3.40"
        )
