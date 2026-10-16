"""Project eligibility filters owner-only saved key metadata over real HTTP views."""

import uuid
from types import SimpleNamespace

import pytest
from accounts.models import User
from data_classes.models import ProjectClass
from django.db import DatabaseError
from django.test import override_settings
from model_registry import runtime_keys
from model_registry.models import DeveloperProviderKey, ModelApproval
from projects.services import DjangoProjectStore

from tests.integration.test_runtime_catalog import catalog as catalog  # noqa: PLC0414 -- pytest fixture re-export


@pytest.fixture(autouse=True)
def fast_passwords():
    with override_settings(
        PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"]
    ):
        yield


@pytest.fixture
def listing(catalog, monkeypatch):
    catalog.path = f"/api/runtime/projects/{catalog.project}/provider-keys"
    ModelApproval.objects.filter(pk="private").update(key_choice="personal")
    ModelApproval.objects.filter(pk="public").update(key_choice="shared")

    def forbidden(*args, **kwargs):
        pytest.fail("Listing registrations must not read keys, files or providers")

    monkeypatch.setattr(runtime_keys, "key_store", forbidden)
    return catalog


def get(listing, **headers):
    return listing.client.get(
        listing.path,
        HTTP_AUTHORIZATION="Bearer " + listing.token,
        **headers,
    )


def row(name, required, status=None):
    return {"id": name, "own_key_required": required, "status": status}


def test_current_project_classes_choices_and_owner_registrations(listing):
    other = User.objects.get(username="first-admin")
    DeveloperProviderKey.objects.create(
        owner=other, model_id="private", key_name="other-private"
    )
    assert get(listing).json() == {
        "project_id": listing.project,
        "models": [row("private", True, "missing")],
    }
    # As with individual status, an old registration is still visible without
    # reading its file or treating its binding as current/provider health.
    DeveloperProviderKey.objects.create(
        owner_id=listing.actor["id"],
        model_id="private",
        key_name="private-file-secret",
        validation_fingerprint="f" * 64,
    )
    response = get(listing)
    assert response.json()["models"] == [row("private", True, "added")]
    assert "no-store" in response["Cache-Control"]
    for secret in (
        "private-file-secret",
        "other-private",
        "f" * 64,
        listing.token,
        str(other.pk),
    ):
        assert secret.encode() not in response.content
    listing.stores.classes.set_enabled(False)
    assert get(listing).json()["models"] == [
        row("private", True, "added"),
        row("public", False),
    ]
    ModelApproval.objects.filter(pk="public").update(key_choice="none")
    assert get(listing).json()["models"][-1] == row("public", False)
    # No stored key names are read into the response, and list is read-only.
    assert DeveloperProviderKey.objects.count() == 2


def test_other_project_class_and_stale_or_unapproved_models_are_excluded(listing):
    other_project = str(uuid.uuid4())
    DjangoProjectStore().register_use(listing.actor["id"], other_project, "Other")
    ProjectClass.objects.create(project_id=other_project, data_class_id="public")
    listing.path = f"/api/runtime/projects/{other_project}/provider-keys"
    assert get(listing).json()["models"] == [row("public", False)]
    listing.path = f"/api/runtime/projects/{listing.project}/provider-keys"
    # Forged claims and a changed current role cannot bypass the class gate.
    listing.stores.identity.change_role(listing.actor["id"], "admin")
    assert get(listing, HTTP_X_ROLE="admin", HTTP_X_DATA_CLASS="Public").json()[
        "models"
    ] == [row("private", True, "missing")]
    listing.resources[0]["revision"] += 1
    assert get(listing).json()["models"] == []


@pytest.mark.parametrize("project", ["invalid", str(uuid.uuid4())])
def test_unknown_project_denied(listing, project):
    listing.path = f"/api/runtime/projects/{project}/provider-keys"
    assert get(listing).status_code == 403


def test_cookie_only_and_invalid_bearer_are_denied(listing):
    listing.client.cookies["keeplane_session"] = listing.token
    for headers in ({}, {"HTTP_AUTHORIZATION": "Bearer invalid"}):
        response = listing.client.get(listing.path, **headers)
        assert response.status_code == 401 and response["WWW-Authenticate"] == "Bearer"


def test_role_withdrawal_revokes_the_previous_session(listing):
    listing.stores.identity.change_role(listing.actor["id"], "admin")
    assert get(listing).status_code == 200
    listing.stores.identity.change_role(listing.actor["id"], "developer")
    assert get(listing, HTTP_X_ROLE="admin").status_code == 401


def test_incomplete_policy_snapshot_returns_no_partial_metadata(listing, monkeypatch):
    monkeypatch.setattr(
        runtime_keys.runtime_views,
        "model_policy",
        lambda: SimpleNamespace(
            eligible_model_ids=lambda _: frozenset({"private", "unknown"})
        ),
    )
    response = get(listing)
    assert response.status_code == 503 and "models" not in response.json()


@pytest.mark.parametrize("withdrawal", ["logout", "password", "disabled"])
def test_authentication_rechecked_under_owner_lock_before_metadata(
    listing, monkeypatch, withdrawal
):
    original = runtime_keys.RuntimeSessionAuthentication.authenticate
    calls = []

    def authenticate(self, request):
        result = original(self, request)
        calls.append(result)
        if len(calls) == 1:
            if withdrawal == "logout":
                listing.stores.identity.logout(listing.token)
            else:
                owner = User.objects.get(pk=listing.actor["id"])
                if withdrawal == "password":
                    owner.set_password("changed-test-password")
                else:
                    owner.is_active = False
                owner.save()
        return result

    monkeypatch.setattr(
        runtime_keys.RuntimeSessionAuthentication, "authenticate", authenticate
    )
    monkeypatch.setattr(
        DeveloperProviderKey.objects,
        "filter",
        lambda **kw: pytest.fail("Withdrawn account read owner rows"),
    )
    assert get(listing).status_code == 401


@pytest.mark.parametrize(
    "body,query", [(b"{}", ""), (b"", "?owner_id=forged"), (b"", "?model_id=private")]
)
def test_body_or_query_fields_refused(listing, body, query):
    response = listing.client.generic(
        "GET", listing.path + query, body, HTTP_AUTHORIZATION="Bearer " + listing.token
    )
    assert response.status_code == 400


def test_outages_return_no_partial_list(listing, monkeypatch):
    listing.state.status = 503
    assert get(listing).status_code == 503
    listing.state.status = 200

    def unavailable(**kwargs):
        raise DatabaseError("private database path/credential")

    monkeypatch.setattr(DeveloperProviderKey.objects, "filter", unavailable)
    response = get(listing)
    assert response.status_code == 503
    assert b"private database" not in response.content
