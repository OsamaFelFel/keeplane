"""Model Registry database records."""

from django.db import models


class ProviderKeyChoice(models.TextChoices):
    NONE = "none", "No key"
    SHARED = "shared", "Shared key"
    PERSONAL = "personal", "Developer's own key"


class ModelApproval(models.Model):
    model_id = models.CharField(max_length=256, primary_key=True)
    key_choice = models.CharField(max_length=16, choices=ProviderKeyChoice.choices)
    approved_classes = models.JSONField(default=list)
    gateway_fingerprint = models.CharField(max_length=128)
    owned_by_keeplane = models.BooleanField(default=False)

    class Meta:
        db_table = "accounts_modelapproval"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(key_choice__in=ProviderKeyChoice.values),
                name="model_key_choice_valid",
            )
        ]


class DeveloperProviderKey(models.Model):
    owner = models.ForeignKey("accounts.User", on_delete=models.PROTECT)
    model_id = models.CharField(max_length=256)
    key_name = models.CharField(max_length=36, default="", blank=True)
    pending_key_name = models.CharField(max_length=36, default="", blank=True)
    validation_fingerprint = models.CharField(max_length=64, default="", blank=True)
    refused = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("owner", "model_id"), name="developer_key_owner_model_unique"
            )
        ]


class PendingProviderKeyDeletion(models.Model):
    directory = models.TextField()
    key_name = models.CharField(max_length=36)
