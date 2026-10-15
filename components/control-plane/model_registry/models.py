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
