from constance.codecs import dumps, loads
from django.conf import settings
from django.db import migrations


def copy_qgis_versions(apps, schema_editor):
    connection = schema_editor.connection
    table = "preferences_sitepreference"
    if table not in connection.introspection.table_names():
        return

    with connection.cursor() as cursor:
        cursor.execute(
            f"SELECT DISTINCT qgis_versions FROM {connection.ops.quote_name(table)}"
        )
        versions = [row[0] for row in cursor.fetchall()]

    if not versions:
        return
    if len(versions) > 1:
        raise RuntimeError(
            "Cannot migrate different SitePreference values to the shared "
            "Constance QGIS_VERSIONS setting. Reconcile the legacy "
            "preferences_sitepreference.qgis_versions values before retrying. "
            "The legacy tables have not been changed."
        )

    Constance = apps.get_model("constance", "Constance")
    key = getattr(settings, "CONSTANCE_DATABASE_PREFIX", "") + "QGIS_VERSIONS"
    stored, created = Constance.objects.using(connection.alias).get_or_create(
        key=key, defaults={"value": dumps(versions[0])}
    )
    if not created and loads(stored.value) != versions[0]:
        raise RuntimeError(
            "Constance QGIS_VERSIONS already differs from SitePreference. "
            "Reconcile the values before retrying; neither value was overwritten."
        )


class Migration(migrations.Migration):
    dependencies = [
        ("plugins", "0029_drop_djangoratings_tables"),
        ("constance", "0003_drop_pickle"),
    ]

    operations = [
        migrations.RunPython(copy_qgis_versions, reverse_code=migrations.RunPython.noop),
    ]
