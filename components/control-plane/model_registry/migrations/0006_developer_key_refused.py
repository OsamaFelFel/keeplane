from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("model_registry", "0005_pending_provider_key_deletion")]

    operations = [
        migrations.AddField(
            model_name="developerproviderkey",
            name="refused",
            field=models.BooleanField(default=False),
        )
    ]
