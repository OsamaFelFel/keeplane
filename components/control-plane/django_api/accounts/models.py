"""Keeplane records in the same database as Django's native sessions."""

import uuid

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.db import models
from django.db.models.functions import Lower


class User(AbstractBaseUser):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # Accounts deliberately use ASCII names. Fix the database comparison locale
    # so uniqueness and sign-in cannot acquire Unicode aliases or locale drift.
    username = models.CharField(max_length=64, unique=True, db_collation="C")
    role = models.CharField(max_length=16, choices=(("admin", "Admin"), ("developer", "Developer")))
    is_active = models.BooleanField(default=True)
    objects = BaseUserManager()
    USERNAME_FIELD = "username"

    class Meta:
        constraints = [
            models.UniqueConstraint(Lower("username"), name="account_username_casefold_unique"),
            models.CheckConstraint(condition=models.Q(role__in=("admin", "developer")), name="account_role_valid"),
        ]


class SessionOwner(models.Model):
    session = models.OneToOneField("sessions.Session", on_delete=models.CASCADE, primary_key=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE)


class LoginBudget(models.Model):
    bucket = models.CharField(max_length=64, primary_key=True)
    attempts = models.PositiveIntegerField(default=0)
    expires_at = models.DateTimeField()


class UserOperation(models.Model):
    id = models.UUIDField(primary_key=True)
    actor_id = models.UUIDField()
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True)


class EditionNote(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, primary_key=True)
    enabled = models.BooleanField(default=True)
    seen = models.BooleanField(default=False)


class Settings(models.Model):
    id = models.PositiveSmallIntegerField(primary_key=True, default=1)
    classes_enabled = models.BooleanField(default=False)

    class Meta:
        constraints = [models.CheckConstraint(condition=models.Q(id=1), name="settings_singleton")]


class AuditOption(models.Model):
    kind = models.CharField(max_length=32, primary_key=True)
    enabled = models.BooleanField(default=False)


class AuditRecord(models.Model):
    kind = models.CharField(max_length=32)
    happened_at = models.DateTimeField(auto_now_add=True)
    actor_id = models.CharField(max_length=64)
    actor_name = models.CharField(max_length=64)
    description = models.TextField()

    class Meta:
        indexes = [models.Index(fields=["kind", "-id"], name="audit_kind_recent")]


class DataClass(models.Model):
    # Starter IDs are human-readable; added classes retain the existing hex ID contract.
    id = models.CharField(max_length=64, primary_key=True)
    name = models.CharField(max_length=80, unique=True)
    position = models.PositiveIntegerField()


class ProjectClass(models.Model):
    project_id = models.CharField(max_length=64, primary_key=True)
    data_class = models.ForeignKey(DataClass, on_delete=models.PROTECT)


class ModelApproval(models.Model):
    model_id = models.CharField(max_length=256, primary_key=True)
    key_choice = models.CharField(max_length=16)
    approved_classes = models.JSONField(default=list)
    gateway_fingerprint = models.CharField(max_length=128)
    owned_by_keeplane = models.BooleanField(default=False)

    class Meta:
        constraints = [models.CheckConstraint(condition=models.Q(key_choice__in=("none", "shared")), name="model_key_choice_valid")]
