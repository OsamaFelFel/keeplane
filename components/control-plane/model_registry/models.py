"""Model Registry database records."""

from django.db import models


class ProviderKeyChoice(models.TextChoices):
    NONE = "none", "No key"
    SHARED = "shared", "Shared key"
    PERSONAL = "personal", "Developer's own key"


class ModelOrigin(models.TextChoices):
    """Where a model Keeplane added runs, for cost estimates (ADR 029)."""

    NOT_RECORDED = "", "Not recorded"
    LOCAL = "local", "Local runner"
    CLOUD = "cloud", "Cloud provider"


class CloudProvider(models.TextChoices):
    OPENAI = "openai", "OpenAI"
    ANTHROPIC = "anthropic", "Anthropic"


class ModelApproval(models.Model):
    model_id = models.CharField(max_length=256, primary_key=True)
    key_choice = models.CharField(max_length=16, choices=ProviderKeyChoice.choices)
    approved_classes = models.JSONField(default=list)
    gateway_fingerprint = models.CharField(max_length=128)
    owned_by_keeplane = models.BooleanField(default=False)
    # The context window a local runner reported when Keeplane added the
    # model, in tokens; null when Keeplane was not told. Admins never enter it.
    context_tokens = models.PositiveIntegerField(null=True, blank=True)
    # Recorded when Keeplane adds the model, so usage can be priced (ADR 029):
    # a local runner is never priced, and a cloud model is looked up by its
    # provider and the provider's own model name. Models set up before this
    # was recorded, or registered directly in the gateway, keep "". The
    # database default lets an app copy from before this change still save an
    # approval during an upgrade.
    origin = models.CharField(
        max_length=8,
        choices=ModelOrigin.choices,
        default="",
        db_default="",
        blank=True,
    )
    provider = models.CharField(
        max_length=16,
        choices=CloudProvider.choices,
        default="",
        db_default="",
        blank=True,
    )
    provider_model = models.CharField(
        max_length=256, default="", db_default="", blank=True
    )
    # When the origin was recorded; usage before then is never priced, so a
    # name reused after removal can't price a local model's tokens.
    origin_recorded_at = models.DateTimeField(null=True, blank=True)
    # True when no developer's usage held this model name yet in the UTC hour
    # the origin was recorded, so that hour holds only this model's tokens and
    # is priced too. Otherwise pricing starts with the next whole hour.
    origin_hour_priced = models.BooleanField(default=False, db_default=False)

    class Meta:
        db_table = "accounts_modelapproval"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(key_choice__in=ProviderKeyChoice.values),
                name="model_key_choice_valid",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        origin="",
                        provider="",
                        provider_model="",
                        origin_recorded_at__isnull=True,
                    )
                    | models.Q(
                        origin="local",
                        provider="",
                        provider_model="",
                        origin_recorded_at__isnull=False,
                    )
                    | (
                        models.Q(
                            origin="cloud",
                            provider__in=CloudProvider.values,
                            origin_recorded_at__isnull=False,
                        )
                        & ~models.Q(provider_model="")
                    )
                ),
                name="model_origin_complete",
            ),
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


class GatewayGuardStatus(models.Model):
    """One managed gateway copy's confirmed guard declaration (ADR 027).

    In Kubernetes the app cannot read a copy's Pod-local guard files, so each
    copy's model enroller records here what it confirmed by readback. The copy
    name is its StatefulSet Pod name. Only that copy's enroller may write its
    row (PostgreSQL row-level security, set up by
    ``manage.py configure_guard_status_access``); the app only reads it.
    ``declaration`` is null, and ``confirmed`` false, while nothing is
    confirmed on that copy.
    """

    copy_name = models.CharField(max_length=63, primary_key=True)
    confirmed = models.BooleanField(default=False)
    declaration = models.JSONField(null=True, blank=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(
                        confirmed=True,
                        declaration__isnull=False,
                        confirmed_at__isnull=False,
                    )
                    | models.Q(
                        confirmed=False,
                        declaration__isnull=True,
                        confirmed_at__isnull=True,
                    )
                ),
                name="guard_status_confirmed_complete",
            )
        ]
