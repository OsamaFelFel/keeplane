from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("model_registry", "0010_model_origin"),
    ]

    operations = [
        migrations.AddField(
            model_name="modelapproval",
            name="origin_hour_priced",
            field=models.BooleanField(db_default=False, default=False),
        ),
    ]
