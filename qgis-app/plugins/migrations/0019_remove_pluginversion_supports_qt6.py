from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("plugins", "0018_pluginversionsecurityscan"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="pluginversion",
            name="supports_qt6",
        ),
    ]
