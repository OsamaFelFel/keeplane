"""Optional OAuth trial: actual Toolkit records and Keeplane account boundaries."""

import uuid
from datetime import timedelta
from types import SimpleNamespace

import pytest
from accounts import authentication
from accounts.cli_credentials import RuntimeIdentity, access_token, bind_issued_token
from accounts.models import CliCredentialBinding, User
from accounts.services import revoke
from common import api
from django.apps import apps
from django.db import DatabaseError, transaction
from django.test import Client, override_settings
from django.utils import timezone
from model_registry import runtime_views

pytestmark = [
    pytest.mark.optional,
    pytest.mark.live,
    pytest.mark.skipif(
        not apps.is_installed("oauth2_provider"),
        reason="Install the separately pinned CLI OAuth trial dependencies",
    ),
]


@pytest.fixture
def oauth(domain_services, monkeypatch):
    from oauth2_provider.models import AccessToken, Application, set_token_value

    native = domain_services.identity
    native.create_user(
        {
            "username": "cli-oauth-developer",
            "role": "developer",
            "password": "trial-password-123",
        }
    )
    owner = User.objects.get(username="cli-oauth-developer")
    app = Application.objects.create(
        client_id="keeplane-cli",
        client_type=Application.CLIENT_PUBLIC,
        authorization_grant_type=Application.GRANT_AUTHORIZATION_CODE,
        redirect_uris="http://127.0.0.1/callback",
        name="Keeplane CLI",
    )

    def issue(user=owner, application=app, scope="runtime", bound=True):
        raw = access_token()
        with transaction.atomic():
            token = AccessToken(
                user=user,
                application=application,
                scope=scope,
                expires=timezone.now() + timedelta(hours=1),
            )
            set_token_value(token, raw)
            token.save()
            if bound:
                bind_issued_token(
                    CliCredentialBinding.Kind.ACCESS,
                    raw,
                    user.pk,
                    user.get_session_auth_hash(),
                )
        return SimpleNamespace(raw=raw, row=token)

    monkeypatch.setattr(authentication, "IDENTITY", native)
    monkeypatch.setattr(runtime_views, "IDENTITY", native)
    monkeypatch.setattr(api, "IDENTITY", native)
    with override_settings(CLI_OAUTH_ENABLED=True, ALLOWED_HOSTS=["testserver"]):
        yield SimpleNamespace(
            native=native,
            identity=RuntimeIdentity(native),
            owner=owner,
            app=app,
            issue=issue,
            client=Client(enforce_csrf_checks=True),
            stores=domain_services,
        )


def test_current_account_and_hashed_storage(oauth):
    issued = oauth.issue()
    issued.row.refresh_from_db()
    assert issued.row.token == ""
    binding = CliCredentialBinding.objects.get(checksum=issued.row.token_checksum)
    assert binding.owner_id == oauth.owner.pk
    assert issued.raw not in binding.checksum + binding.auth_hash
    assert oauth.identity.authenticated_user(issued.raw).pk == oauth.owner.pk
    User.objects.filter(pk=oauth.owner.pk).update(role="admin")
    assert oauth.identity.session(issued.raw)["role"] == "admin"
    oauth.client.cookies["keeplane_session"] = issued.raw
    assert oauth.client.get("/api/identity").status_code == 401


@pytest.fixture
def project_policy(oauth, monkeypatch):
    from data_classes.models import ProjectClass
    from model_registry.fingerprints import fingerprint
    from model_registry.policy import DjangoModelPolicy
    from projects.services import DjangoProjectStore

    project = str(uuid.uuid4())
    DjangoProjectStore().register_use(oauth.owner.pk, project, "OAuth trial")
    oauth.stores.classes.set_enabled(True)
    ProjectClass.objects.create(project_id=project, data_class_id="confidential")
    resources = [{"id": "private", "revision": 1}]
    oauth.stores.catalog.approve(
        "private", ["Confidential"], fingerprint("private", resources)
    )
    state = SimpleNamespace(status=200)
    gateway = SimpleNamespace(
        models=lambda: (state.status, {"data": [{"id": "private"}]}),
        resources=lambda: (state.status, {"resources": resources}),
    )
    monkeypatch.setattr(
        runtime_views, "model_policy", lambda: DjangoModelPolicy(gateway)
    )
    return SimpleNamespace(
        project=project, resources=resources, gateway=gateway, state=state
    )


def test_oauth_catalog_rechecks_current_project_and_model_policy(oauth, project_policy):
    issued = oauth.issue()
    headers = {"HTTP_AUTHORIZATION": "Bearer " + issued.raw}
    path = f"/api/runtime/projects/{project_policy.project}/models"
    assert oauth.client.get(path, **headers).json()["models"] == [{"id": "private"}]
    project_policy.resources[0]["revision"] = 2
    assert oauth.client.get(path, **headers).json()["models"] == []
    project_policy.state.status = 503
    assert oauth.client.get(path, **headers).status_code == 503


def test_oauth_project_registration_derives_current_account(oauth):
    from projects.models import ProjectUse

    issued = oauth.issue()
    project = str(uuid.uuid4())
    response = oauth.client.post(
        "/api/runtime/projects",
        data={"project_id": project, "name": "CLI OAuth"},
        content_type="application/json",
        HTTP_AUTHORIZATION="Bearer " + issued.raw,
    )
    assert response.status_code == 200
    assert ProjectUse.objects.get(project_id=project).user_id == oauth.owner.pk


def test_gateway_callback_uses_same_current_oauth_identity(
    oauth, project_policy, monkeypatch, tmp_path
):
    from model_registry import runtime_callback

    issued = oauth.issue()
    key = "synthetic-gateway-credential-" + "x" * 32
    key_file = tmp_path / "gateway-key"
    key_file.write_text(key)
    monkeypatch.setattr(runtime_callback, "IDENTITY", oauth.native)
    monkeypatch.setattr(runtime_callback, "model_policy", runtime_views.model_policy)
    monkeypatch.setattr(runtime_callback, "MODEL_GATEWAY", project_policy.gateway)

    def authorize():
        return oauth.client.post(
            "/internal/runtime/authorize",
            data={"project_id": project_policy.project, "model_id": "private"},
            content_type="application/json",
            HTTP_AUTHORIZATION="Bearer " + issued.raw,
            HTTP_X_KEEPLANE_GATEWAY_CREDENTIAL=key,
        )

    with override_settings(RUNTIME_AUTHORIZER_KEY_FILE=str(key_file)):
        response = authorize()
        assert response.status_code == 200
        assert response.json() == {
            "actor_id": str(oauth.owner.pk),
            "project_id": project_policy.project,
            "model_id": "private",
        }
        project_policy.resources[0]["revision"] = 2
        assert authorize().status_code == 403
        project_policy.resources[0]["revision"] = 1
        revoke(oauth.owner)
        assert authorize().status_code == 401


@pytest.mark.parametrize(
    "withdrawal", ["disabled", "password", "expired", "binding", "flag"]
)
def test_withdrawal_on_next_request(oauth, withdrawal):
    issued = oauth.issue()
    if withdrawal == "disabled":
        User.objects.filter(pk=oauth.owner.pk).update(is_active=False)
    elif withdrawal == "password":
        oauth.owner.set_password("replacement-trial-password")
        oauth.owner.save(update_fields=["password"])
    elif withdrawal == "expired":
        issued.row.expires = timezone.now() - timedelta(seconds=1)
        issued.row.save(update_fields=["expires"])
    elif withdrawal == "binding":
        CliCredentialBinding.objects.all().delete()
    with override_settings(CLI_OAUTH_ENABLED=withdrawal != "flag"):
        response = oauth.client.delete(
            "/api/runtime/session", HTTP_AUTHORIZATION="Bearer " + issued.raw
        )
    assert response.status_code == 401
    assert response["WWW-Authenticate"] == "Bearer"


@pytest.mark.parametrize(
    "invalid", ["scope", "unbound", "client", "type", "grant", "plaintext"]
)
def test_unapproved_credentials_never_resolve(oauth, invalid):
    issued = oauth.issue(
        scope="other" if invalid == "scope" else "runtime", bound=invalid != "unbound"
    )
    if invalid == "client":
        oauth.app.client_id = "unapproved-client"
    elif invalid == "type":
        oauth.app.client_type = oauth.app.CLIENT_CONFIDENTIAL
    elif invalid == "grant":
        oauth.app.authorization_grant_type = oauth.app.GRANT_PASSWORD
    elif invalid == "plaintext":
        type(issued.row).objects.filter(pk=issued.row.pk).update(token=issued.raw)
    oauth.app.save()
    assert oauth.identity.authenticated_user(issued.raw) is None


def test_logout_is_explicit_and_revokes_paired_refresh_only(oauth):
    from oauth2_provider.models import RefreshToken, set_token_value

    first, second = oauth.issue(), oauth.issue()
    browser = oauth.native.login(oauth.owner.username, "trial-password-123")
    raw_refresh = "kpr_" + "r" * 43
    with transaction.atomic():
        refresh = RefreshToken(
            user=oauth.owner, application=oauth.app, access_token=first.row
        )
        set_token_value(refresh, raw_refresh)
        refresh.save()
        bind_issued_token(
            CliCredentialBinding.Kind.REFRESH,
            raw_refresh,
            oauth.owner.pk,
            oauth.owner.get_session_auth_hash(),
        )
    oauth.client.cookies["keeplane_session"] = browser
    assert oauth.client.delete("/api/runtime/session").status_code == 401
    response = oauth.client.delete(
        "/api/runtime/session", HTTP_AUTHORIZATION="Bearer " + first.raw
    )
    assert response.status_code == 204
    refresh.refresh_from_db()
    assert refresh.token == "" and refresh.revoked is not None
    assert oauth.identity.session(first.raw) is None
    assert oauth.identity.session(second.raw) is not None
    assert oauth.native.session(browser) is not None
    assert not CliCredentialBinding.objects.filter(
        checksum=refresh.token_checksum
    ).exists()


def test_global_revoke_rollback_and_disabled_feature_cleanup(oauth):
    from oauth2_provider.models import DeviceGrant, Grant

    issued = oauth.issue()
    expires = timezone.now() + timedelta(minutes=1)
    Grant.objects.create(
        user=oauth.owner,
        application=oauth.app,
        code="synthetic-code",
        expires=expires,
        redirect_uri="http://127.0.0.1/callback",
    )
    DeviceGrant.objects.create(
        user=oauth.owner,
        client_id="keeplane-cli-device",
        device_code="synthetic-device",
        user_code="ABCD-EFGH",
        expires=expires,
    )
    browser = oauth.native.login(oauth.owner.username, "trial-password-123")
    with pytest.raises(RuntimeError), transaction.atomic():
        revoke(oauth.owner)
        raise RuntimeError("rollback")
    assert oauth.identity.session(issued.raw) is not None
    assert oauth.native.session(browser) is not None
    with override_settings(CLI_OAUTH_ENABLED=False):
        revoke(oauth.owner)
    assert not type(issued.row).objects.filter(pk=issued.row.pk).exists()
    assert not CliCredentialBinding.objects.exists()
    assert not Grant.objects.exists() and not DeviceGrant.objects.exists()
    assert oauth.native.session(browser) is None


def test_account_removal_with_acceptance_disabled_preserves_other_owner(oauth):
    first = oauth.issue()
    other = User.objects.get(username="first-admin")
    second = oauth.issue(user=other)
    with override_settings(CLI_OAUTH_ENABLED=False):
        oauth.native.delete_user(str(oauth.owner.pk))
    assert not type(first.row).objects.filter(pk=first.row.pk).exists()
    assert not CliCredentialBinding.objects.filter(owner_id=oauth.owner.pk).exists()
    assert oauth.identity.session(first.raw) is None
    assert oauth.identity.session(second.raw)["id"] == str(other.pk)


def test_issuance_requires_same_locked_account_state(oauth):
    previous = oauth.owner.get_session_auth_hash()
    oauth.owner.set_password("changed-before-token-issuance")
    oauth.owner.save(update_fields=["password"])
    with pytest.raises(ValueError, match="account changed"), transaction.atomic():
        bind_issued_token(
            CliCredentialBinding.Kind.ACCESS, access_token(), oauth.owner.pk, previous
        )
    assert not CliCredentialBinding.objects.exists()


def test_storage_failure_is_unavailable_not_anonymous(oauth, monkeypatch):
    from oauth2_provider.models import AccessToken

    issued = oauth.issue()

    def unavailable(*args, **kwargs):
        raise DatabaseError("unavailable test database")

    monkeypatch.setattr(AccessToken.objects, "select_related", unavailable)
    response = oauth.client.delete(
        "/api/runtime/session", HTTP_AUTHORIZATION="Bearer " + issued.raw
    )
    assert response.status_code == 503
    assert issued.raw not in response.content.decode()
