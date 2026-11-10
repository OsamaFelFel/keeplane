from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("model_registry", "0009_gateway_guard_status"),
    ]

    operations = [
        migrations.AddField(
            model_name="modelapproval",
            name="origin",
            field=models.CharField(
                blank=True,
                choices=[
                    ("", "Not recorded"),
                    ("local", "Local runner"),
                    ("cloud", "Cloud provider"),
                ],
                db_default="",
                default="",
                max_length=8,
            ),
        ),
        migrations.AddField(
            model_name="modelapproval",
            name="origin_recorded_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="modelapproval",
            name="provider",
            field=models.CharField(
                blank=True,
                choices=[("openai", "OpenAI"), ("anthropic", "Anthropic")],
                db_default="",
                default="",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="modelapproval",
            name="provider_model",
            field=models.CharField(
                blank=True, db_default="", default="", max_length=256
            ),
        ),
        migrations.AddConstraint(
            model_name="modelapproval",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(
                        ("origin", ""),
                        ("origin_recorded_at__isnull", True),
                        ("provider", ""),
                        ("provider_model", ""),
                    ),
                    models.Q(
                        ("origin", "local"),
                        ("origin_recorded_at__isnull", False),
                        ("provider", ""),
                        ("provider_model", ""),
                    ),
                    models.Q(
                        ("origin", "cloud"),
                        ("origin_recorded_at__isnull", False),
                        ("provider__in", ["openai", "anthropic"]),
                        models.Q(("provider_model", ""), _negated=True),
                    ),
                    _connector="OR",
                ),
                name="model_origin_complete",
            ),
        ),
    ]
