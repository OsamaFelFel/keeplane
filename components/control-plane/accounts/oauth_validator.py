"""Toolkit hooks for current Keeplane accounts; endpoint owns the owner lock."""

from django.db import transaction
from oauth2_provider.models import Grant, RefreshToken
from oauth2_provider.oauth2_validators import OAuth2Validator
from oauth2_provider.views import AuthorizationView, TokenView
from oauthlib.oauth2 import InvalidGrantError

from .cli_credentials import bind_issued_token, checksum, current_binding
from .models import CliCredentialBinding, User


class KeeplaneOAuthValidator(OAuth2Validator):
    def _owner(self, kind, value, owner_id):
        if not transaction.get_connection().in_atomic_block:
            raise RuntimeError("Issue CLI credentials inside the owner transaction")
        owner = User.objects.select_for_update().filter(pk=owner_id).first()
        return owner if current_binding(kind, value, owner) else None

    def _create_authorization_code(self, request, code, expires=None):
        grant = super()._create_authorization_code(request, code, expires)
        bind_issued_token(
            CliCredentialBinding.Kind.CODE,
            code["code"],
            request.user.pk,
            request.user.get_session_auth_hash(),
        )
        return grant

    def validate_code(self, client_id, code, client, request, *args, **kwargs):
        grant = Grant.objects.filter(code=code, application=client).first()
        owner = (
            self._owner(CliCredentialBinding.Kind.CODE, code, grant.user_id)
            if grant
            else None
        )
        if owner is None or not super().validate_code(
            client_id, code, client, request, *args, **kwargs
        ):
            return False
        request.user = owner
        return True

    def validate_refresh_token(self, value, client, request, *args, **kwargs):
        row = RefreshToken.objects.filter(
            token_checksum=checksum(value), application=client
        ).first()
        owner = (
            self._owner(CliCredentialBinding.Kind.REFRESH, value, row.user_id)
            if row
            else None
        )
        # Retain revoked-row bindings so Toolkit's family replay protection runs.
        if owner is None or not super().validate_refresh_token(
            value, client, request, *args, **kwargs
        ):
            return False
        request.user = owner
        return True

    def _save_bearer_token(self, token, request, *args, **kwargs):
        kind, value = (
            (CliCredentialBinding.Kind.CODE, request.code)
            if request.grant_type == "authorization_code"
            else (CliCredentialBinding.Kind.REFRESH, request.refresh_token)
        )
        owner = self._owner(kind, value, request.user.pk)
        if owner is None:
            raise InvalidGrantError(request=request)
        super()._save_bearer_token(token, request, *args, **kwargs)
        for kind, name in (
            (CliCredentialBinding.Kind.ACCESS, "access_token"),
            (CliCredentialBinding.Kind.REFRESH, "refresh_token"),
        ):
            bind_issued_token(
                kind, token[name], owner.pk, owner.get_session_auth_hash()
            )

    def invalidate_authorization_code(self, client_id, code, request, *args, **kwargs):
        super().invalidate_authorization_code(client_id, code, request, *args, **kwargs)
        CliCredentialBinding.objects.filter(
            checksum=checksum(code), kind="code"
        ).delete()


class KeeplaneAuthorizationView(AuthorizationView):
    validator_class = KeeplaneOAuthValidator
    template_name = "accounts/cli_consent.html"


class KeeplaneTokenView(TokenView):
    validator_class = KeeplaneOAuthValidator
