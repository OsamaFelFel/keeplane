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
    # The context window a local runner reported when Keeplane added the
    # model, in tokens; null when Keeplane was not told. Admins never enter it.
    context_tokens = models.PositiveIntegerField(null=True, blank=True)

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


class ComplexityLevel(models.TextChoices):
    SIMPLE = "simple", "Simple"
    STANDARD = "standard", "Standard"
    COMPLEX = "complex", "Complex"


class ComplexityLevelChoice(models.Model):
    """An admin's pick for one complexity level; absent means Keeplane picks."""

    level = models.CharField(
        max_length=16, primary_key=True, choices=ComplexityLevel.choices
    )
    model_id = models.CharField(max_length=256)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(level__in=ComplexityLevel.values),
                name="complexity_level_valid",
            )
        ]


class Persona(models.TextChoices):
    """The predefined personas an agent starts from (D24)."""

    ARCHITECT = "architect", "Architect"
    DEVELOPER = "developer", "Developer"
    FRONTEND = "frontend", "Frontend"


class PersonaRule(models.Model):
    """An admin's rule sending one persona's work to one model (Spec 004 ST15)."""

    persona = models.CharField(max_length=16, primary_key=True, choices=Persona.choices)
    model_id = models.CharField(max_length=256)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(persona__in=Persona.values),
                name="persona_rule_persona_valid",
            )
        ]
