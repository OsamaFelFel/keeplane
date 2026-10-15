"""Adopt the tables created by accounts.0001 without recreating them."""

from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [("accounts", "0001_initial")]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.CreateModel(
                    name="AuditOption",
                    fields=[
                        (
                            "kind",
                            models.CharField(
                                max_length=32, primary_key=True, serialize=False
                            ),
                        ),
                        ("enabled", models.BooleanField(default=False)),
                    ],
                    options={
                        "db_table": "accounts_auditoption",
                    },
                ),
                migrations.CreateModel(
                    name="AuditRecord",
                    fields=[
                        (
                            "id",
                            models.BigAutoField(
                                auto_created=True,
                                primary_key=True,
                                serialize=False,
                                verbose_name="ID",
                            ),
                        ),
                        ("kind", models.CharField(max_length=32)),
                        ("happened_at", models.DateTimeField(auto_now_add=True)),
                        ("actor_id", models.CharField(max_length=64)),
                        ("actor_name", models.CharField(max_length=64)),
                        ("description", models.TextField()),
                    ],
                    options={
                        "db_table": "accounts_auditrecord",
                        "indexes": [
                            models.Index(
                                fields=["kind", "-id"], name="audit_kind_recent"
                            )
                        ],
                    },
                ),
            ]
        )
    ]
