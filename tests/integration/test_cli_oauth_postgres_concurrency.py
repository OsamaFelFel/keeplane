"""Actual PostgreSQL row locks around maintained code/device token issuance."""

import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Event, local
from urllib.parse import urlencode

import pytest
from accounts.models import CliCredentialBinding, User
from accounts.services import revoke
from django.apps import apps
from django.db import connection, connections, transaction
from django.test import Client

from tests.integration.test_cli_oauth_browser import FORM, browser_flow  # noqa: F401
from tests.integration.test_cli_oauth_device import device  # noqa: F401

pytestmark = [pytest.mark.optional, pytest.mark.live, pytest.mark.django_db(transaction=True),
              pytest.mark.skipif(not apps.is_installed("oauth2_provider") or connection.vendor != "postgresql",
                                 reason="Run with the OAuth trial graph and a disposable PostgreSQL database")]


def form_for(channel, journey):
    if channel == "browser":
        issued = journey.flow.code()
        return {"grant_type": "authorization_code", "client_id": "keeplane-cli",
                "code": issued.returned["code"][0], "code_verifier": issued.verifier,
                "redirect_uri": issued.parameters["redirect_uri"]}
    issued = journey.start()
    journey.approve(issued)
    journey.due(issued)
    return {"grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            "client_id": "keeplane-cli-device", "device_code": issued.value["device_code"]}


def exchange(form, label):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT set_config('application_name', %s, false)", [label])
            cursor.execute("SET statement_timeout = '15s'")
        response = Client(enforce_csrf_checks=True, HTTP_HOST="127.0.0.1:3000").post(
            "/oauth/token/", urlencode(form), content_type=FORM)
        return response.status_code, response.json()
    finally:
        connections.close_all()


def wait_for_database_lock(future, label):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        with connection.cursor() as cursor:
            cursor.execute("SELECT wait_event_type FROM pg_stat_activity WHERE application_name = %s", [label])
            if any(row[0] == "Lock" for row in cursor.fetchall()):
                assert not future.done(), "The second request must still be waiting"
                return
        assert not future.done(), "The request finished without waiting on PostgreSQL"
        time.sleep(0.02)
    pytest.fail("No PostgreSQL row-lock wait was observed")


def concurrent_exchanges(form, monkeypatch, *, device_grant=False):
    from accounts import oauth_device_protocol, oauth_views

    module = oauth_device_protocol if device_grant else oauth_views
    original = module.fixed_client
    held, release, worker = Event(), Event(), local()
    first_label, second_label = "cli-first-" + uuid.uuid4().hex, "cli-second-" + uuid.uuid4().hex

    def gated(*args, **kwargs):
        # Called after the real owner SELECT FOR UPDATE, before client locking.
        if getattr(worker, "first", False):
            held.set()
            assert release.wait(10), "The fixture did not release its first owner lock"
        return original(*args, **kwargs)

    def request(label, *, first=False):
        worker.first = first
        return exchange(form, label)

    monkeypatch.setattr(module, "fixed_client", gated)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(request, first_label, first=True)
        try:
            assert held.wait(5), "The first request did not reach the locked owner"
            second = pool.submit(request, second_label)
            wait_for_database_lock(second, second_label)
        finally:
            release.set()
        return first.result(timeout=20), second.result(timeout=20)


@pytest.mark.parametrize("channel", ["browser", "device"])
def test_only_one_concurrent_exchange_consumes_the_grant(channel, device, monkeypatch):  # noqa: F811
    from oauth2_provider.models import AccessToken, DeviceGrant, Grant, RefreshToken

    first, second = concurrent_exchanges(form_for(channel, device), monkeypatch,
                                        device_grant=channel == "device")
    assert (first[0], second[0]) == (200, 400)
    assert device.flow.identity.session(first[1]["access_token"])["id"] == str(device.flow.owner.pk)
    assert AccessToken.objects.count() == RefreshToken.objects.count() == 1
    assert not Grant.objects.exists() and not DeviceGrant.objects.exists()
    assert CliCredentialBinding.objects.filter(owner=device.flow.owner, kind="access").count() == 1
    assert CliCredentialBinding.objects.filter(owner=device.flow.owner, kind="refresh").count() == 1
    assert not CliCredentialBinding.objects.filter(kind__in=["code", "device"]).exists()


@pytest.mark.parametrize("channel", ["browser", "device"])
def test_concurrent_refresh_replay_withdraws_the_rotated_family(channel, device, monkeypatch):  # noqa: F811
    form = form_for(channel, device)
    status, issued = exchange(form, "cli-issue-" + uuid.uuid4().hex)
    assert status == 200
    refresh = {"grant_type": "refresh_token", "client_id": form["client_id"],
               "refresh_token": issued["refresh_token"]}
    first, second = concurrent_exchanges(refresh, monkeypatch)
    assert (first[0], second[0]) == (200, 400)
    assert device.flow.identity.session(issued["access_token"]) is None
    assert device.flow.identity.session(first[1]["access_token"]) is None
    assert exchange({**refresh, "refresh_token": first[1]["refresh_token"]},
                    "cli-replay-check-" + uuid.uuid4().hex)[0] == 400


@pytest.mark.parametrize("channel", ["browser", "device"])
def test_global_withdrawal_while_issuance_waits_prevents_new_tokens(channel, device):  # noqa: F811
    from oauth2_provider.models import AccessToken, RefreshToken

    form = form_for(channel, device)
    label = "cli-withdrawal-waiter-" + uuid.uuid4().hex
    with ThreadPoolExecutor(max_workers=1) as pool:
        with transaction.atomic():
            owner = User.objects.select_for_update().get(pk=device.flow.owner.pk)
            future = pool.submit(exchange, form, label)
            wait_for_database_lock(future, label)
            revoke(owner)
        assert future.result(timeout=20)[0] == 400
    assert not AccessToken.objects.exists() and not RefreshToken.objects.exists()
    assert not CliCredentialBinding.objects.filter(owner=device.flow.owner).exists()
