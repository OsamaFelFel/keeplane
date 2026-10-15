"""Move Django model ownership without changing existing tables or records."""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0001_initial"),
        ("audit", "0001_initial"),
        ("data_classes", "0001_initial"),
        ("model_registry", "0001_initial"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.DeleteModel("ProjectClass"),
                migrations.DeleteModel("DataClass"),
                migrations.DeleteModel("Settings"),
                migrations.DeleteModel("ModelApproval"),
                migrations.DeleteModel("AuditOption"),
                migrations.DeleteModel("AuditRecord"),
                *[
                    migrations.AlterModelTable(name, "accounts_" + name)
                    for name in (
                        "user",
                        "loginbudget",
                        "sessionowner",
                        "useroperation",
                        "editionnote",
                    )
                ],
            ]
        )
    ]
