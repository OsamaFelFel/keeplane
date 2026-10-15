"""Accounts database records."""

from django.db import models
import uuid
from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.db.models.functions import Lower


class User(AbstractBaseUser):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # Accounts deliberately use ASCII names. Fix the database comparison locale
    # so uniqueness and sign-in cannot acquire Unicode aliases or locale drift.
    username = models.CharField(max_length=64, unique=True, db_collation="C")
    role = models.CharField(
        max_length=16, choices=(("admin", "Admin"), ("developer", "Developer"))
    )
    is_active = models.BooleanField(default=True)
    objects = BaseUserManager()
    USERNAME_FIELD = "username"

    class Meta:
        db_table = "accounts_user"
        constraints = [
            models.UniqueConstraint(
                Lower("username"), name="account_username_casefold_unique"
            ),
            models.CheckConstraint(
                condition=models.Q(role__in=("admin", "developer")),
                name="account_role_valid",
            ),
        ]


class SessionOwner(models.Model):
    session = models.OneToOneField(
        "sessions.Session", on_delete=models.CASCADE, primary_key=True
    )
    user = models.ForeignKey(User, on_delete=models.CASCADE)

    class Meta:
        db_table = "accounts_sessionowner"


class LoginBudget(models.Model):
    bucket = models.CharField(max_length=64, primary_key=True)
    attempts = models.PositiveIntegerField(default=0)
    expires_at = models.DateTimeField()

    class Meta:
        db_table = "accounts_loginbudget"


class UserOperation(models.Model):
    id = models.UUIDField(primary_key=True)
    actor_id = models.UUIDField()
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True)

    class Meta:
        db_table = "accounts_useroperation"


class EditionNote(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, primary_key=True)
    enabled = models.BooleanField(default=True)
    seen = models.BooleanField(default=False)

    class Meta:
        db_table = "accounts_editionnote"
