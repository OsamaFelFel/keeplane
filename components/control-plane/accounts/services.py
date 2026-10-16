"""Local identity port implemented with Django users and database sessions."""

from datetime import timedelta
from math import ceil
from pathlib import Path
import uuid

from django.contrib.auth import get_user, login
from django.contrib.auth.hashers import check_password, make_password
from django.contrib.sessions.backends.db import SessionStore
from django.contrib.sessions.models import Session
from django.db import IntegrityError, transaction
from django.db.models.functions import Lower
from django.http import HttpRequest
from django.utils import timezone

from .contracts import (
    IdentityError,
    LoginThrottled,
    LOGIN_ATTEMPTS,
    LOGIN_WINDOW_SECONDS,
    SESSION_SECONDS,
    USERNAME_PATTERN,
    login_bucket,
    pagination,
    public_user,
)
from .models import EditionNote, LoginBudget, SessionOwner, User, UserOperation
from common.storage import storage_service


DUMMY_PASSWORD = make_password("not-a-real-account")


def user_dict(user):
    return {"id": str(user.pk), "username": user.username, "role": user.role}


def revoke(user):
    from .cli_credentials import revoke_user

    with transaction.atomic():
        User.objects.select_for_update().get(pk=user.pk)
        Session.objects.filter(
            session_key__in=SessionOwner.objects.filter(user=user).values("session_id")
        ).delete()
        revoke_user(user)


def identifier(value):
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        raise IdentityError(404, "Account not found")


@storage_service
class DjangoIdentity:
    def __init__(self, password_file, audit):
        self.audit = audit
        password = Path(password_file).read_text().strip()
        if not 12 <= len(password) <= 256:
            raise RuntimeError("First-admin password must be 12–256 characters")
        with transaction.atomic():
            # The unique username constraint serializes simultaneous first starts.
            user, _ = User.objects.get_or_create(
                username="first-admin",
                defaults={"password": make_password(password), "role": "admin"},
            )
            user = User.objects.select_for_update().get(pk=user.pk)
            if (
                not user.check_password(password)
                or user.role != "admin"
                or not user.is_active
            ):
                user.set_password(password)
                user.role, user.is_active = "admin", True
                user.save(update_fields=["password", "role", "is_active"])
                revoke(user)
                LoginBudget.objects.filter(pk=login_bucket("first-admin")).delete()

    def reserve_login(self, username):
        now = timezone.now()
        with transaction.atomic():
            LoginBudget.objects.filter(expires_at__lte=now).delete()
            row, _ = LoginBudget.objects.get_or_create(
                bucket=login_bucket(username),
                defaults={"expires_at": now + timedelta(seconds=LOGIN_WINDOW_SECONDS)},
            )
            row = LoginBudget.objects.select_for_update().get(pk=row.pk)
            if row.attempts >= LOGIN_ATTEMPTS:
                raise LoginThrottled(
                    max(1, ceil((row.expires_at - now).total_seconds()))
                )
            row.attempts += 1
            row.save(update_fields=["attempts"])

    def login(self, username, password):
        if (
            not isinstance(username, str)
            or not USERNAME_PATTERN.fullmatch(username)
            or not isinstance(password, str)
        ):
            raise IdentityError(401, "Invalid username or password")
        self.reserve_login(username)
        with transaction.atomic():
            user = (
                User.objects.select_for_update()
                .filter(username__iexact=username)
                .first()
            )
            valid = (
                user.check_password(password)
                if user
                else check_password(password, DUMMY_PASSWORD)
            )
            if not user or not valid or not user.is_active:
                raise IdentityError(401, "Invalid username or password")
            request = HttpRequest()
            request.session = SessionStore()
            login(request, user, backend="django.contrib.auth.backends.ModelBackend")
            request.session.set_expiry(SESSION_SECONDS)
            request.session.save()
            SessionOwner.objects.create(
                session_id=request.session.session_key, user=user
            )
            if user.username == "first-admin":
                self.audit.record_break_glass(user_dict(user))
            LoginBudget.objects.filter(pk=login_bucket(username)).delete()
            # The caller can return the cookie only after both writes commit.
            token = request.session.session_key
        return token

    def authenticated_user(self, token):
        if not token or not isinstance(token, str) or len(token) > 200:
            return None
        request = HttpRequest()
        request.session = SessionStore(session_key=token)
        user = get_user(request)
        return user if user.is_authenticated and user.is_active else None

    def session(self, token):
        user = self.authenticated_user(token)
        return user_dict(user) if user else None

    def logout(self, token):
        if token and isinstance(token, str) and len(token) <= 200:
            with transaction.atomic():
                owner_id = SessionOwner.objects.filter(session_id=token).values_list("user_id", flat=True).first()
                if owner_id is None:
                    owner = self.authenticated_user(token)
                    owner_id = owner.pk if owner else None
                if owner_id is not None:
                    User.objects.select_for_update().filter(pk=owner_id).first()
                SessionStore(session_key=token).delete()

    def users(self, query):
        page, size = pagination(query)
        search = query.get("search", [""])[0].strip()
        if len(search) > 80:
            raise IdentityError(400, "Search is too long")
        rows = User.objects.filter(username__icontains=search).order_by(
            Lower("username"), "id"
        )
        total = rows.count()
        found = list(rows[(page - 1) * size : page * size + 1])
        return {
            "users": [public_user(user_dict(user)) for user in found[:size]],
            "page": page,
            "page_size": size,
            "total": total,
            "has_more": len(found) > size,
        }

    def create_user(self, body, actor_id=None):
        username, password, role = (
            body.get("username"),
            body.get("password"),
            body.get("role"),
        )
        if not isinstance(username, str) or not USERNAME_PATTERN.fullmatch(username):
            raise IdentityError(
                400,
                "Username must be 3–64 letters, numbers, dots, dashes or underscores",
            )
        if not isinstance(password, str) or not 12 <= len(password) <= 256:
            raise IdentityError(400, "Password must be 12–256 characters")
        if role not in ("admin", "developer"):
            raise IdentityError(400, "Choose admin or developer")
        operation_id = body.get("operation_id")
        if operation_id is not None:
            try:
                operation_id = uuid.UUID(operation_id)
            except (ValueError, TypeError, AttributeError):
                raise IdentityError(400, "Operation ID must be a UUID")
            if not actor_id:
                raise IdentityError(400, "Operation needs a signed-in admin")
        try:
            with transaction.atomic():
                operation = None
                if operation_id is not None:
                    operation, _ = UserOperation.objects.get_or_create(
                        pk=operation_id, defaults={"actor_id": actor_id}
                    )
                    operation = UserOperation.objects.select_for_update().get(
                        pk=operation.pk
                    )
                    if str(operation.actor_id) != str(actor_id):
                        raise IdentityError(
                            409, "Operation ID belongs to a different request"
                        )
                    if operation.user_id:
                        prior = operation.user
                        if (
                            prior.username.lower() != username.lower()
                            or prior.role != role
                            or not prior.check_password(password)
                        ):
                            raise IdentityError(
                                409, "Operation ID belongs to a different request"
                            )
                        return public_user(user_dict(prior))
                user = User(username=username, role=role)
                user.set_password(password)
                user.save(force_insert=True)
                if operation:
                    operation.user = user
                    operation.save(update_fields=["user"])
                return public_user(user_dict(user))
        except IntegrityError:
            raise IdentityError(409, "That name already exists")

    def user_operation(self, operation_id, actor_id):
        try:
            operation_id = uuid.UUID(operation_id)
        except (ValueError, TypeError, AttributeError):
            raise IdentityError(400, "Operation ID must be a UUID")
        row = (
            UserOperation.objects.select_related("user")
            .filter(pk=operation_id, actor_id=actor_id)
            .first()
        )
        if not row or not row.user_id:
            return {"status": "not_found"}
        return {"status": "created", "user": public_user(user_dict(row.user))}

    def change_role(self, user_id, role):
        if role not in ("admin", "developer"):
            raise IdentityError(400, "Choose admin or developer")
        with transaction.atomic():
            user = (
                User.objects.select_for_update().filter(pk=identifier(user_id)).first()
            )
            if not user:
                raise IdentityError(404, "Account not found")
            if user.username == "first-admin":
                raise IdentityError(
                    403, "The first admin's role is managed at infrastructure level"
                )
            user.role = role
            user.save(update_fields=["role"])
            if role != "admin":
                revoke(user)
        return public_user(user_dict(user))

    def delete_user(self, user_id):
        with transaction.atomic():
            user = (
                User.objects.select_for_update().filter(pk=identifier(user_id)).first()
            )
            if not user:
                raise IdentityError(404, "Account not found")
            if user.username == "first-admin":
                raise IdentityError(403, "The first admin cannot be removed")
            revoke(user)
            user.delete()
        return {"removed": True}

    def edition_note(self, user_id):
        row = EditionNote.objects.filter(user_id=user_id).first()
        return {"enabled": row.enabled if row else True}

    def set_edition_note(self, user_id, enabled):
        if type(enabled) is not bool:
            raise IdentityError(400, "Choose whether to show the Enterprise note")
        with transaction.atomic():
            row, _ = EditionNote.objects.get_or_create(user_id=user_id)
            row = EditionNote.objects.select_for_update().get(pk=row.pk)
            if not row.enabled and enabled:
                row.seen = False
            row.enabled = enabled
            row.save(update_fields=["enabled", "seen"])
        return {"enabled": enabled}

    def consume_edition_note(self, user_id):
        with transaction.atomic():
            row, _ = EditionNote.objects.get_or_create(user_id=user_id)
            row = EditionNote.objects.select_for_update().get(pk=row.pk)
            show = row.enabled and not row.seen
            if show:
                row.seen = True
                row.save(update_fields=["seen"])
        return {"show": show}
