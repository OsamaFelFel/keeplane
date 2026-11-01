"""Data Classes database records."""

from django.db import models


class Settings(models.Model):
    id = models.PositiveSmallIntegerField(primary_key=True, default=1)
    classes_enabled = models.BooleanField(default=False)
    # Spec 005 ST20: off by default; the class is kept while detection is off.
    # The database default keeps writers from before this column working.
    detection_enabled = models.BooleanField(default=False, db_default=False)
    detection_class = models.ForeignKey(
        "DataClass",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )

    class Meta:
        db_table = "accounts_settings"
        constraints = [
            models.CheckConstraint(condition=models.Q(id=1), name="settings_singleton")
        ]


class DataClass(models.Model):
    # Starter IDs are human-readable; added classes retain the existing hex ID contract.
    id = models.CharField(max_length=64, primary_key=True)
    name = models.CharField(max_length=80, unique=True)
    position = models.PositiveIntegerField()

    class Meta:
        db_table = "accounts_dataclass"


class ProjectClass(models.Model):
    project_id = models.CharField(max_length=64, primary_key=True)
    data_class = models.ForeignKey(DataClass, on_delete=models.PROTECT)

    class Meta:
        db_table = "accounts_projectclass"
