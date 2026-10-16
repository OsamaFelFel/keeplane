"""Actual Toolkit metadata gates enabled readiness without taking row locks."""

import json

import pytest
from accounts import oauth_views
from django.apps import apps
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import OperationalError, connection
from django.test.utils import CaptureQueriesContext

from tests.integration.test_readiness import probe

pytestmark = [
    pytest.mark.optional, pytest.mark.live, pytest.mark.django_db,
    pytest.mark.skipif(not apps.is_installed("oauth2_provider"),
                       reason="Install the pinned sign-in trial graph"),
]


@pytest.fixture
def clients(settings):
    from oauth2_provider.models import Application

    settings.CLI_OAUTH_ENABLED = True
    call_command("register_cli_client", verbosity=0)
    call_command("register_cli_client", device=True, verbosity=0)
    return Application


def readonly_probe():
    with CaptureQueriesContext(connection) as queries:
        response = probe()
    assert queries and all(item["sql"].lstrip().upper().startswith("SELECT") for item in queries)
    assert all("FOR UPDATE" not in item["sql"].upper() for item in queries)
    return response


def test_matching_clients_ready_without_locking(clients, monkeypatch):
    def forbid_lock(*args, **kwargs):
        raise AssertionError("Readiness must not lock sign-in clients")

    monkeypatch.setattr(clients.objects, "select_for_update", forbid_lock)
    assert readonly_probe().status_code == 200


@pytest.mark.parametrize("client_id", [oauth_views.CLIENT_ID, oauth_views.DEVICE_ID])
def test_missing_client_refuses_readiness_without_recreating_it(clients, client_id):
    clients.objects.filter(client_id=client_id).delete()
    before = list(clients.objects.values())
    assert readonly_probe().status_code == 503
    assert list(clients.objects.values()) == before


@pytest.mark.parametrize("client_id", [oauth_views.CLIENT_ID, oauth_views.DEVICE_ID])
@pytest.mark.parametrize("changes", [
    {"client_type": "confidential"}, {"redirect_uris": "https://untrusted.example.test"},
])
def test_drifted_client_stays_unready_and_registration_refuses_overwrite(clients, client_id, changes):
    clients.objects.filter(client_id=client_id).update(**changes)
    before = list(clients.objects.values())
    assert readonly_probe().status_code == 503
    with pytest.raises(CommandError, match="existing CLI client differs"):
        call_command("register_cli_client", device=client_id == oauth_views.DEVICE_ID)
    assert list(clients.objects.values()) == before


def test_client_lookup_outage_is_generic_and_recovers(clients, monkeypatch):
    original = clients.objects.filter

    def unavailable(*args, **kwargs):
        raise OperationalError("password=synthetic-secret")

    monkeypatch.setattr(clients.objects, "filter", unavailable)
    response = probe()
    assert response.status_code == 503
    assert json.loads(response.content) == {"app": "unavailable"}
    monkeypatch.setattr(clients.objects, "filter", original)
    assert readonly_probe().status_code == 200


def test_authorization_check_keeps_its_locking_default(clients, monkeypatch):
    original = clients.objects.select_for_update
    calls = []

    def locked():
        calls.append(True)
        return original()

    monkeypatch.setattr(clients.objects, "select_for_update", locked)
    assert oauth_views.fixed_client()
    assert calls == [True]
