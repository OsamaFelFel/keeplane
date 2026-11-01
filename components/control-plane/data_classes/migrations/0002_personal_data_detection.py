"""Personal-data detection settings (Spec 005 ST20): off, class kept while off."""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("data_classes", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="settings",
            name="detection_class",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="+",
                to="data_classes.dataclass",
            ),
        ),
        migrations.AddField(
            model_name="settings",
            name="detection_enabled",
            field=models.BooleanField(db_default=False, default=False),
        ),
    ]
