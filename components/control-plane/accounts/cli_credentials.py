"""Current-account resolution for the optional CLI OAuth integration trial."""

import hashlib
import re
import secrets

from django.apps import apps
from django.conf import settings
from django.db import transaction
from django.utils.crypto import constant_time_compare

from .models import CliCredentialBinding, User

CLIENT_IDS = frozenset({"keeplane-cli", "keeplane-cli-device"})
ACCESS_PREFIX = "kpc_"
ACCESS_PATTERN = re.compile(r"kpc_[A-Za-z0-9_-]{43}")


def access_token(request=None):
    return ACCESS_PREFIX + secrets.token_urlsafe(32)


def refresh_token(request=None):
    return "kpr_" + secrets.token_urlsafe(32)


def checksum(value):
    return hashlib.sha256(value.encode("ascii")).hexdigest()


def bind_issued_token(kind, value, owner_id, expected_auth_hash):
    """Trusted issuer only: preserve the password state used for authorization.

    The issuer must lock the owner before rechecking the live authorizing
    session/grant and retain that lock through issuance. This password hash
    alone does not detect a global revoke or refresh-token rotation.
    """
    if not transaction.get_connection().in_atomic_block:
        raise RuntimeError("Bind CLI credentials inside the issuance transaction")
    if (
        kind not in CliCredentialBinding.Kind.values
        or not isinstance(value, str)
        or not re.fullmatch(r"[A-Za-z0-9_-]{16,200}", value)
    ):
        raise ValueError("Invalid CLI credential binding")
    owner = User.objects.select_for_update().get(pk=owner_id)
    if not owner.is_active or not constant_time_compare(
        expected_auth_hash, owner.get_session_auth_hash()
    ):
        raise ValueError("The account changed during authorization")
    CliCredentialBinding.objects.create(
        checksum=checksum(value),
        kind=kind,
        owner=owner,
        auth_hash=expected_auth_hash,
    )


def current_binding(kind, value, owner):
    if not owner or not owner.is_active:
        return False
    return CliCredentialBinding.objects.filter(
        checksum=checksum(value),
        kind=kind,
        owner=owner,
        auth_hash=owner.get_session_auth_hash(),
    ).exists()


def resolve_user(value):
    if (
        not getattr(settings, "CLI_OAUTH_ENABLED", False)
        or not isinstance(value, str)
        or not ACCESS_PATTERN.fullmatch(value)
    ):
        return None
    from oauth2_provider.models import get_access_token_model

    token = (
        get_access_token_model()
        .objects.select_related("user", "application")
        .filter(token_checksum=checksum(value))
        .first()
    )
    if not token or token.token or not token.is_valid(["runtime"]):
        return None
    application = token.application
    if (
        not application
        or application.client_id not in CLIENT_IDS
        or application.client_type != application.CLIENT_PUBLIC
        or application.authorization_grant_type
        != (
            application.GRANT_AUTHORIZATION_CODE
            if application.client_id == "keeplane-cli"
            else application.GRANT_DEVICE_CODE
        )
        or not application.is_usable(None)
    ):
        return None
    # Re-read current account state; a token never snapshots role or activity.
    owner = User.objects.filter(pk=token.user_id).first()
    return (
        owner
        if current_binding(CliCredentialBinding.Kind.ACCESS, value, owner)
        else None
    )


def revoke_user(owner):
    """Called under the same owner lock as native session/password withdrawal."""
    CliCredentialBinding.objects.filter(owner=owner).delete()
    if apps.is_installed("oauth2_provider"):
        from oauth2_provider.models import (
            get_access_token_model,
            get_device_grant_model,
            get_grant_model,
            get_refresh_token_model,
        )

        get_refresh_token_model().objects.filter(user=owner).delete()
        get_access_token_model().objects.filter(user=owner).delete()
        get_grant_model().objects.filter(user=owner).delete()
        get_device_grant_model().objects.filter(user=owner).delete()


class RuntimeIdentity:
    """Keep CLI credentials separate from browser-cookie identity."""

    def __init__(self, native):
        self.native = native

    def authenticated_user(self, value):
        return (
            resolve_user(value)
            if isinstance(value, str) and value.startswith(ACCESS_PREFIX)
            else self.native.authenticated_user(value)
        )

    def session(self, value):
        if not isinstance(value, str) or not value.startswith(ACCESS_PREFIX):
            return self.native.session(value)
        owner = resolve_user(value)
        return (
            {"id": str(owner.pk), "username": owner.username, "role": owner.role}
            if owner
            else None
        )

    def logout(self, value):
        if not isinstance(value, str) or not value.startswith(ACCESS_PREFIX):
            return self.native.logout(value)
        if not getattr(
            settings, "CLI_OAUTH_ENABLED", False
        ) or not ACCESS_PATTERN.fullmatch(value):
            return
        from oauth2_provider.models import (
            get_access_token_model,
            get_refresh_token_model,
            revoke_access_token,
        )

        with transaction.atomic():
            token = (
                get_access_token_model()
                .objects.select_related("application")
                .filter(token_checksum=checksum(value))
                .first()
            )
            if token:
                User.objects.select_for_update().filter(pk=token.user_id).first()
                refresh_checksums = list(
                    get_refresh_token_model()
                    .objects.filter(access_token=token)
                    .values_list("token_checksum", flat=True)
                )
                revoke_access_token(token)
                CliCredentialBinding.objects.filter(
                    checksum__in=refresh_checksums,
                    kind=CliCredentialBinding.Kind.REFRESH,
                ).delete()
            CliCredentialBinding.objects.filter(checksum=checksum(value)).delete()
