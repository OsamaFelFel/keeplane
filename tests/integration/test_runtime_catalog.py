"""Real sessions and stored project/class policy protect the HTTP catalog."""

from datetime import timedelta
from types import SimpleNamespace
import uuid

import pytest
from django.contrib.sessions.models import Session
from django.db import DatabaseError
from django.test import Client, override_settings
from django.utils import timezone

from accounts import authentication
from accounts.models import User
from data_classes.models import ProjectClass
from model_registry import runtime_views
from model_registry.fingerprints import fingerprint
from model_registry.policy import DjangoModelPolicy
from projects.models import ProjectUse
from projects.services import DjangoProjectStore


@pytest.fixture
def catalog(domain_services, monkeypatch):
    stores, password = domain_services, "catalog-test-password"
    actor = stores.identity.create_user(
        {"username": "catalog-developer", "role": "developer", "password": password}
    )
    token = stores.identity.login(actor["username"], password)
    project = str(uuid.uuid4())
    # Another organization account registered it; usage is not membership.
    DjangoProjectStore().register_use(
        User.objects.get(username="first-admin").pk, project, "Catalog"
    )
    stores.classes.set_enabled(True)
    ProjectClass.objects.create(project_id=project, data_class_id="confidential")
    resources = [
        {"id": name, "revision": 1} for name in ("private", "public", "outside")
    ]
    for name, classes in (("private", ["Confidential"]), ("public", ["Public"])):
        stores.catalog.approve(name, classes, fingerprint(name, resources))
    state = SimpleNamespace(status=200)
    gateway = SimpleNamespace(
        models=lambda: (state.status, {"data": [{"id": r["id"]} for r in resources]}),
        resources=lambda: (state.status, {"resources": resources}),
    )
    monkeypatch.setattr(authentication, "IDENTITY", stores.identity)
    monkeypatch.setattr(
        runtime_views, "model_policy", lambda: DjangoModelPolicy(gateway)
    )
    with override_settings(ALLOWED_HOSTS=["testserver"]):
        yield SimpleNamespace(
            client=Client(enforce_csrf_checks=True),
            actor=actor,
            token=token,
            path=f"/api/runtime/projects/{project}/models",
            project=project,
            stores=stores,
            state=state,
            resources=resources,
        )


def get(catalog, token=None):
    return catalog.client.get(
        catalog.path, HTTP_AUTHORIZATION="Bearer " + (token or catalog.token)
    )


def test_catalog_uses_organization_access_and_current_class(catalog):
    assert not ProjectUse.objects.filter(user_id=catalog.actor["id"]).exists()
    response = get(catalog)
    assert response.status_code == 200
    assert response.json() == {
        "project_id": catalog.project,
        "models": [{"id": "private"}],
    }
    assert "no-store" in response["Cache-Control"]
    assert catalog.token not in response.content.decode()
    catalog.stores.classes.set_enabled(False)
    assert get(catalog).json()["models"] == [{"id": "private"}, {"id": "public"}]


@pytest.mark.parametrize(
    "header",
    [None, "Basic invalid", "Bearer invalid", "Bearer a b", 'Bearer quoted"value'],
)
def test_cookie_and_claim_headers_cannot_replace_bearer_auth(catalog, header):
    catalog.client.cookies["keeplane_session"] = catalog.token
    headers = {
        "HTTP_X_USER_ID": catalog.actor["id"],
        "HTTP_X_ROLE": "admin",
        "HTTP_X_DATA_CLASS": "Public",
    }
    if header is not None:
        headers["HTTP_AUTHORIZATION"] = header
    response = catalog.client.get(catalog.path, **headers)
    assert response.status_code == 401 and response["WWW-Authenticate"] == "Bearer"
    assert "no-store" in response["Cache-Control"]


@pytest.mark.parametrize("withdrawal", ["expired", "logout", "disabled", "password"])
def test_session_withdrawal_is_visible_on_next_http_read(catalog, withdrawal):
    assert get(catalog).status_code == 200
    if withdrawal == "expired":
        Session.objects.filter(pk=catalog.token).update(
            expire_date=timezone.now() - timedelta(seconds=1)
        )
    elif withdrawal == "logout":
        catalog.stores.identity.logout(catalog.token)
    else:
        user = User.objects.get(pk=catalog.actor["id"])
        if withdrawal == "disabled":
            user.is_active = False
            user.save(update_fields=["is_active"])
        else:
            user.set_password("replacement-catalog-password")
            user.save(update_fields=["password"])
    assert get(catalog).status_code == 401


def test_admin_cannot_bypass_class_and_withdrawn_models_disappear(catalog):
    User.objects.filter(pk=catalog.actor["id"]).update(role="admin")
    assert get(catalog).json()["models"] == [{"id": "private"}]
    catalog.resources[0]["revision"] = 2
    assert get(catalog).json()["models"] == []


@pytest.mark.parametrize("context", ["not-a-uuid", str(uuid.uuid4())])
def test_unknown_context_is_denied(catalog, context):
    catalog.path = f"/api/runtime/projects/{context}/models"
    assert get(catalog).status_code == 403


def test_gateway_and_storage_outages_do_not_return_stale_catalog(catalog, monkeypatch):
    assert get(catalog).status_code == 200
    catalog.state.status = 503
    assert get(catalog).status_code == 503

    def unavailable(*args, **kwargs):
        raise DatabaseError("Unavailable database")

    monkeypatch.setattr(User.objects, "filter", unavailable)
    assert get(catalog).status_code == 503


def test_non_loopback_http_installation_refuses_credentials(catalog):
    with override_settings(PUBLIC_ORIGIN="http://keeplane.example.test"):
        assert get(catalog).status_code == 503
