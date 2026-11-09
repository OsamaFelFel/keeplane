"""The server gives signed-in CLIs the installer's gateway address (Spec 009 ST30, ADR 030).

Cases RGA-01 to RGA-04 in runtime-gateway-address-cases.md.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from accounts import authentication
from django.test import Client, override_settings
from model_registry import runtime_views

ROOT = Path(__file__).resolve().parents[2]
GATEWAY = "https://keeplane.example/v1"
STARTUP = (
    "import django; django.setup(); from django.conf import settings; "
    "print(settings.GATEWAY_PUBLIC_URL)"
)


@pytest.fixture
def signed_in(domain_services, monkeypatch):
    identity, password = domain_services.identity, "gateway-address-password"
    identity.create_user(
        {"username": "gateway-developer", "role": "developer", "password": password}
    )
    token = identity.login("gateway-developer", password)
    monkeypatch.setattr(authentication, "IDENTITY", identity)
    monkeypatch.setattr(runtime_views, "IDENTITY", identity)
    with override_settings(ALLOWED_HOSTS=["testserver"]):
        yield identity, token, Client(enforce_csrf_checks=True)


# RGA-01
def test_a_signed_in_cli_gets_the_configured_gateway_address(signed_in):
    identity, token, client = signed_in
    with override_settings(GATEWAY_PUBLIC_URL=GATEWAY):
        response = client.get(
            "/api/runtime/session",
            HTTP_AUTHORIZATION="Bearer " + token,
            HTTP_HOST="testserver",
            HTTP_X_FORWARDED_HOST="attacker.example",
        )
    assert response.status_code == 200
    assert response.json() == {**identity.session(token), "gateway_url": GATEWAY}
    assert "no-store" in response["Cache-Control"]


# RGA-02
def test_an_unconfigured_address_is_null_not_guessed(signed_in):
    identity, token, client = signed_in
    with override_settings(GATEWAY_PUBLIC_URL=None):
        response = client.get(
            "/api/runtime/session",
            HTTP_AUTHORIZATION="Bearer " + token,
            HTTP_X_FORWARDED_HOST="keeplane.example",
            HTTP_X_FORWARDED_PROTO="https",
        )
    assert response.status_code == 200
    assert response.json() == {**identity.session(token), "gateway_url": None}


# RGA-03
@pytest.mark.parametrize("header", [None, "Bearer invalid", "Basic invalid", "revoked"])
def test_without_a_live_cli_sign_in_no_address_is_given(signed_in, header):
    identity, token, client = signed_in
    client.cookies["keeplane_session"] = token
    if header == "revoked":
        identity.logout(token)
        header = "Bearer " + token
    headers = {} if header is None else {"HTTP_AUTHORIZATION": header}
    with override_settings(GATEWAY_PUBLIC_URL=GATEWAY):
        response = client.get("/api/runtime/session", **headers)
    assert response.status_code == 401
    assert GATEWAY not in response.content.decode()


# RGA-04
@pytest.mark.parametrize(
    ("value", "started", "message"),
    [
        ("http://127.0.0.1:5000/v1/", "http://127.0.0.1:5000/v1", ""),
        ("", "None", ""),
        (
            "http://keeplane.example/v1",
            None,
            "must use HTTPS unless the gateway is on this machine",
        ),
        ("https://keeplane.example/v1/chat/completions", None, "ending in /v1"),
    ],
)
def test_the_server_reads_the_setting_once_at_start_up(value, started, message):
    env = dict(
        os.environ,
        KEEPLANE_GATEWAY_PUBLIC_URL=value,
        DJANGO_SETTINGS_MODULE="config.test_settings",
        PYTHONPATH=os.pathsep.join([str(ROOT), str(ROOT / "components/control-plane")]),
    )
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            STARTUP,
        ],
        check=False,
        cwd=ROOT / "components/control-plane",
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if started is None:
        assert result.returncode != 0
        assert (
            "KEEPLANE_GATEWAY_PUBLIC_URL" in result.stderr and message in result.stderr
        )
        assert value not in result.stdout
    else:
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == started
