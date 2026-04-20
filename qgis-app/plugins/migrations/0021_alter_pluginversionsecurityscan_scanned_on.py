import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("plugins", "0020_pluginversion_validation_status"),
    ]

    operations = [
        migrations.AlterField(
            model_name="pluginversionsecurityscan",
            name="scanned_on",
            field=models.DateTimeField(
                default=django.utils.timezone.now,
                verbose_name="Scanned on",
            ),
        ),
    ]
