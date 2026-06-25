import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("plugins", "0024_pluginemailcommunication"),
    ]

    operations = [
        migrations.AddField(
            model_name="pluginversion",
            name="qt6_checked_on",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="pluginversion",
            name="qt6_logs",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="pluginversion",
            name="qt6_status",
            field=models.CharField(
                choices=[
                    ("not_run", "Not run"),
                    ("pending", "Pending"),
                    ("compatible", "Compatible"),
                    ("not_compatible", "Not compatible"),
                ],
                db_index=True,
                default="not_run",
                max_length=20,
                verbose_name="Qt6 status",
            ),
        ),
        migrations.AlterField(
            model_name="pluginversionsecurityscan",
            name="scanned_on",
            field=models.DateTimeField(
                default=django.utils.timezone.now,
                editable=False,
                verbose_name="Scanned on",
            ),
        ),
    ]