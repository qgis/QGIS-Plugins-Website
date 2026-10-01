from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("plugins", "0027_merge_20260712_2333"),
    ]

    operations = [
        migrations.AddField(
            model_name="pluginversion",
            name="deprecated_status",
            field=models.CharField(
                choices=[
                    ("not_run", "Not run"),
                    ("pending", "Pending"),
                    ("no_deprecated", "No deprecated"),
                    ("has_deprecated", "Has deprecated"),
                ],
                db_index=True,
                default="not_run",
                max_length=20,
                verbose_name="Deprecated status",
            ),
        ),
        migrations.AddField(
            model_name="pluginversion",
            name="deprecated_logs",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="pluginversion",
            name="deprecated_checked_on",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
