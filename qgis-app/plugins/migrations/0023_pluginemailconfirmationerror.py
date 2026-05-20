# Generated migration

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("plugins", "0022_emailconfirmation"),
    ]

    operations = [
        migrations.CreateModel(
            name="PluginEmailConfirmationError",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "email",
                    models.EmailField(
                        db_index=True,
                        max_length=254,
                        verbose_name="Email address",
                    ),
                ),
                (
                    "plugins",
                    models.TextField(
                        help_text="Comma-separated list of plugin package names.",
                        verbose_name="Plugins",
                    ),
                ),
                ("error", models.TextField(verbose_name="Error message")),
                (
                    "occurred_at",
                    models.DateTimeField(
                        auto_now_add=True,
                        verbose_name="Occurred at",
                    ),
                ),
            ],
            options={
                "verbose_name": "Plugin Email Confirmation Error",
                "verbose_name_plural": "Plugin Email Confirmation Errors",
                "ordering": ["-occurred_at"],
            },
        ),
    ]
