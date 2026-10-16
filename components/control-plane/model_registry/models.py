"""Model Registry database records."""

from django.db import models


class ModelApproval(models.Model):
    model_id = models.CharField(max_length=256, primary_key=True)
    key_choice = models.CharField(max_length=16)
    approved_classes = models.JSONField(default=list)
    gateway_fingerprint = models.CharField(max_length=128)
    owned_by_keeplane = models.BooleanField(default=False)

    class Meta:
        db_table = "accounts_modelapproval"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(key_choice__in=("none", "shared")),
                name="model_key_choice_valid",
            )
        ]


class DeveloperProviderKey(models.Model):
    owner = models.ForeignKey("accounts.User", on_delete=models.PROTECT)
    model_id = models.CharField(max_length=256)
    key_name = models.CharField(max_length=36, default="", blank=True)
    pending_key_name = models.CharField(max_length=36, default="", blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("owner", "model_id"), name="developer_key_owner_model_unique"
            )
        ]
