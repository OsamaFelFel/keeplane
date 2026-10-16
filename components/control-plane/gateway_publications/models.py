"""Retained generation reservations; none of these states enables dispatch."""

from django.db import models


class DefinitionGeneration(models.Model):
    generation = models.UUIDField(primary_key=True, editable=False)
    model_id = models.CharField(max_length=256)
    raw_fingerprint = models.CharField(max_length=64)
    wiring_digest = models.CharField(max_length=64)
    envelope_digest = models.CharField(max_length=64, default="", blank=True)
    envelope = models.JSONField(default=dict)
    state = models.CharField(max_length=16, default="reserved")

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    state__in=("reserved", "prepared", "retired", "failed")
                ),
                name="definition_generation_state_valid",
            ),
            models.UniqueConstraint(
                fields=("model_id",),
                condition=models.Q(state="prepared"),
                name="one_prepared_generation_per_model",
            ),
        ]
