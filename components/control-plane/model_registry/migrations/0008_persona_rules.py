from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("model_registry", "0007_complexity_levels")]

    operations = [
        migrations.CreateModel(
            name="PersonaRule",
            fields=[
                (
                    "persona",
                    models.CharField(
                        choices=[
                            ("architect", "Architect"),
                            ("developer", "Developer"),
                            ("frontend", "Frontend"),
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
                            ("persona__in", ["architect", "developer", "frontend"])
                        ),
                        name="persona_rule_persona_valid",
                    )
                ]
            },
        ),
    ]
