from django.db import migrations, models

TABLE = "model_registry_gatewayguardstatus"


def restrict_writes(apps, schema_editor):
    """In PostgreSQL, only the table owner can write until access is set up.

    Row-level security with a read-only policy keeps the app's default table
    grants from writing any copy's row. ``manage.py
    configure_guard_status_access`` later replaces this policy with the app's
    read and each copy's own-row write (ADR 027).
    """
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute(f"ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY")
    schema_editor.execute(
        f"CREATE POLICY guard_status_read ON {TABLE} FOR SELECT USING (true)"
    )


class Migration(migrations.Migration):
    dependencies = [("model_registry", "0008_persona_rules")]

    operations = [
        migrations.CreateModel(
            name="GatewayGuardStatus",
            fields=[
                (
                    "copy_name",
                    models.CharField(max_length=63, primary_key=True, serialize=False),
                ),
                ("confirmed", models.BooleanField(default=False)),
                ("declaration", models.JSONField(blank=True, null=True)),
                ("confirmed_at", models.DateTimeField(blank=True, null=True)),
                ("updated_at", models.DateTimeField()),
            ],
            options={
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(
                            models.Q(
                                ("confirmed", True),
                                ("confirmed_at__isnull", False),
                                ("declaration__isnull", False),
                            ),
                            models.Q(
                                ("confirmed", False),
                                ("confirmed_at__isnull", True),
                                ("declaration__isnull", True),
                            ),
                            _connector="OR",
                        ),
                        name="guard_status_confirmed_complete",
                    )
                ],
            },
        ),
        migrations.RunPython(restrict_writes, migrations.RunPython.noop),
    ]
