from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("model_registry", "0006_developer_key_refused")]

    operations = [
        migrations.AddField(
            model_name="modelapproval",
            name="context_tokens",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.CreateModel(
            name="ComplexityLevelChoice",
            fields=[
                (
                    "level",
                    models.CharField(
                        choices=[
                            ("simple", "Simple"),
                            ("standard", "Standard"),
                            ("complex", "Complex"),
                        ],
                        max_length=16,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("model_id", models.CharField(max_length=256)),
            ],
            options={
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(
                            ("level__in", ["simple", "standard", "complex"])
                        ),
                        name="complexity_level_valid",
                    )
                ]
            },
        ),
    ]
