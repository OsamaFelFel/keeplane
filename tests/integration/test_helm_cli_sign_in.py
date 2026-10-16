"""Opt-in installed-wheel authentication on two actual Helm app copies."""

import hashlib
import json
import os
import ssl
from pathlib import Path

import pytest

from tests.fixtures.helm_sign_in import HelmSignIn
from tests.fixtures.helm_sign_in_client import InstalledClient

ROOT = Path(__file__).resolve().parents[2]
pytestmark = [pytest.mark.live, pytest.mark.optional, pytest.mark.infrastructure]


@pytest.fixture(scope="module")
def helm_sign_in(tmp_path_factory):
    if os.environ.get("KEEPLANE_HELM_SIGN_IN_REQUIRED") != "1":
        pytest.skip("Explicitly select the isolated Helm sign-in acceptance")
    required = (
        "IMAGE",
        "IMAGE_ID",
        "WHEEL",
        "WHEEL_SHA256",
        "KUBECONFIG",
        "CONTEXT",
        "HELM",
    )
    settings = {name: os.environ["KEEPLANE_HELM_SIGN_IN_" + name] for name in required}
    wheel = Path(settings["WHEEL"]).resolve(strict=True)
    assert hashlib.sha256(wheel.read_bytes()).hexdigest() == settings["WHEEL_SHA256"]
    directory = tmp_path_factory.mktemp("helm-cli-sign-in")
    directory.chmod(0o700)
    source = Path(os.environ.get("KEEPLANE_HELM_SIGN_IN_SOURCE", ROOT)).resolve(
        strict=True
    )
    fixture = HelmSignIn(
        directory,
        source,
        settings["IMAGE"],
        settings["IMAGE_ID"],
        settings["KUBECONFIG"],
        settings["CONTEXT"],
        settings["HELM"],
    )
    fixture.report["cases"] = []
    try:
        fixture.install()
        assert fixture.sql("SELECT COUNT(*) FROM oauth2_provider_application") == "2"
        client = InstalledClient(
            directory,
            wheel,
            fixture.ca,
            fixture.origin,
            "helm-developer",
            "synthetic-helm-password",
        )
        raw, _ = client.request("/api/auth-options")
        client.request(
            "/api/session",
            {"username": "first-admin", "password": fixture.password},
            csrf=json.loads(raw)["csrf_token"],
        )
        raw, _ = client.request("/api/auth-options")
        client.request(
            "/api/users",
            {
                "username": client.username,
                "password": client.password,
                "role": "developer",
            },
            csrf=json.loads(raw)["csrf_token"],
            expected=201,
        )
        fixture.client = client
        fixture.report["wheel_sha256"] = settings["WHEEL_SHA256"]
        fixture.report["installed_package_files_verified"] = client.installed_files
        observed = json.loads(
            fixture.app_script(
                "from django.db import connection\nimport json\nwith connection.cursor() as cursor:\n cursor.execute('SELECT current_user, ssl FROM pg_stat_ssl WHERE pid=pg_backend_pid()'); print(json.dumps(cursor.fetchone()))"
            ).stdout
        )
        assert observed == ["keeplane_app", True]
        fixture.report["runtime_database_role_and_verified_tls"] = True
        # The test CA must not be trusted implicitly by the host.
        with pytest.raises(ssl.SSLCertVerificationError):
            import socket

            with socket.create_connection(
                fixture.edge.server_address, timeout=3
            ) as connection:
                ssl.create_default_context().wrap_socket(
                    connection, server_hostname="127.0.0.1"
                )
        yield fixture
        assert len(fixture.report["cases"]) == 3
        fixture.report["completed"] = True
    finally:
        try:
            if not fixture.report["completed"] and fixture.created:
                fixture.failure_diagnostics()
            fixture.close()
        finally:
            fixture.report["requests"] = fixture.edge.observations
            if hasattr(fixture, "client"):
                fixture.report["commands"] = fixture.client.commands
            destination = (
                Path(os.environ["KEEPLANE_TEST_REPORT_DIR"]) / "helm-cli-sign-in.json"
            )
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(json.dumps(fixture.report, indent=2) + "\n")
            destination.chmod(0o600)


@pytest.mark.parametrize("channel", ["browser", "device"])
def test_installed_login_refresh_and_logout_across_helm_copies(helm_sign_in, channel):
    fixture, client = helm_sign_in, helm_sign_in.client
    fixture.route(0)
    profile = fixture.directory / ("profile-" + channel)
    client.login(channel, profile, fixture.route)
    original = client.credential(profile)
    fixture.route(1)
    actor = json.loads(client.command("whoami", profile))
    assert actor["username"] == "helm-developer" and actor["role"] == "developer"
    client.command("refresh", profile)
    current = client.credential(profile)
    rotated = current["access_token"] != original["access_token"]
    assert rotated, "Refresh did not rotate the credential"
    fixture.route(0)
    assert json.loads(client.command("whoami", profile)) == actor
    assert client.credential_status(original) == 401
    fixture.route(1)
    client.command("logout", profile)
    assert not (profile / "credential.json").exists()
    for copy in (0, 1):
        fixture.route(copy)
        assert client.credential_status(current) == 401
        assert client.credential_status(current, refresh=True) == 400
    output = fixture.logs() + b"\n".join(client.output)
    assert not any(
        value.encode() in output
        for credential in (original, current)
        for value in (credential["access_token"], credential["refresh_token"])
    )
    fixture.report["cases"].append(
        {
            "channel": channel,
            "cross_copy_identity_refresh_logout": True,
            "old_and_current_credentials_revoked": True,
            "ordinary_logs_and_cli_output_clean": True,
        }
    )


def test_external_migration_requires_read_only_client_prerequisites(helm_sign_in):
    fixture, client = helm_sign_in, helm_sign_in.client
    fixture.values["app"]["postgres"]["migration"]["enabled"] = False
    fixture.chart(upgrade=True)
    hooks = fixture.run(
        fixture.helm,
        "--kubeconfig",
        fixture.kubeconfig,
        "--kube-context",
        fixture.context,
        "-n",
        fixture.namespace,
        "get",
        "hooks",
        "trial",
    ).stdout
    assert b"accounts-migrate" not in hooks
    fixture.app_script(
        "from oauth2_provider.models import Application\nApplication.objects.all().delete()"
    )
    for copy in (0, 1):
        fixture.route(copy)
        raw, _ = client.request("/health/ready", expected=503)
        assert json.loads(raw) == {"app": "unavailable"}
    assert fixture.sql("SELECT COUNT(*) FROM oauth2_provider_application") == "0"
    fixture.external_registration()
    assert fixture.sql("SELECT COUNT(*) FROM oauth2_provider_application") == "2"
    for copy in (0, 1):
        fixture.route(copy)
        client.request("/health/ready")
    fixture.sql(
        "UPDATE oauth2_provider_application SET skip_authorization=true WHERE client_id='keeplane-cli-device'"
    )
    for copy in (0, 1):
        fixture.route(copy)
        client.request("/health/ready", expected=503)
    result = fixture.app_script(
        "from django.core.management import call_command\ncall_command('register_cli_client', device=True)",
        check=False,
    )
    assert result.returncode != 0, "Registration must refuse altered client metadata"
    assert (
        fixture.sql(
            "SELECT skip_authorization FROM oauth2_provider_application WHERE client_id='keeplane-cli-device'"
        )
        == "t"
    )
    fixture.sql(
        "UPDATE oauth2_provider_application SET skip_authorization=false WHERE client_id='keeplane-cli-device'"
    )
    for copy in (0, 1):
        fixture.route(copy)
        client.request("/health/ready")
    fixture.report["cases"].append(
        {
            "external_migration": True,
            "no_automatic_migration_hook": True,
            "missing_and_altered_clients_block_readiness_without_writes": True,
            "explicit_operator_registration_restores_readiness": True,
        }
    )
