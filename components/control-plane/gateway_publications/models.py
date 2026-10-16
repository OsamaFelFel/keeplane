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


class DefinitionPublication(models.Model):
    generation = models.OneToOneField(
        DefinitionGeneration, primary_key=True, on_delete=models.PROTECT
    )
    mode = models.CharField(max_length=16)
    raw_fingerprint = models.CharField(max_length=64)
    envelope_digest = models.CharField(max_length=64)
    state = models.CharField(max_length=24, default="started")
    targets = models.JSONField(default=dict)
    failure = models.CharField(max_length=80, default="", blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    state__in=("started", "failed", "partial", "readback_complete")
                ),
                name="definition_publication_state_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(mode__in=("managed", "existing")),
                name="definition_publication_mode_valid",
            ),
        ]
