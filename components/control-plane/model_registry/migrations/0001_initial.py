"""Adopt the table created by accounts.0001 without recreating it."""

from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [("accounts", "0001_initial")]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.CreateModel(
                    name="ModelApproval",
                    fields=[
                        (
                            "model_id",
                            models.CharField(
                                max_length=256, primary_key=True, serialize=False
                            ),
                        ),
                        ("key_choice", models.CharField(max_length=16)),
                        ("approved_classes", models.JSONField(default=list)),
                        ("gateway_fingerprint", models.CharField(max_length=128)),
                        ("owned_by_keeplane", models.BooleanField(default=False)),
                    ],
                    options={
                        "db_table": "accounts_modelapproval",
                        "constraints": [
                            models.CheckConstraint(
                                condition=models.Q(
                                    ("key_choice__in", ("none", "shared"))
                                ),
                                name="model_key_choice_valid",
                            )
                        ],
                    },
                ),
            ]
        )
    ]
