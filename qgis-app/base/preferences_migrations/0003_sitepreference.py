import django.db.models.deletion
import django.db.models.manager
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("preferences", "0002_auto_20181220_0803")]

    operations = [
        migrations.CreateModel(
            name="SitePreference",
            fields=[
                (
                    "preferences_ptr",
                    models.OneToOneField(
                        auto_created=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        parent_link=True,
                        primary_key=True,
                        serialize=False,
                        to="preferences.preferences",
                    ),
                ),
                (
                    "qgis_versions",
                    models.TextField(
                        blank=True,
                        default="",
                        help_text="QGIS versions that will be used to generate the plugins_xml, separated by comma.",
                    ),
                ),
            ],
            bases=("preferences.preferences",),
            managers=[("singleton", django.db.models.manager.Manager())],
        ),
    ]
