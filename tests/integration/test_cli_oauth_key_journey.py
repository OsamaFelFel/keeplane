"""Actual browser-issued CLI credentials manage server-held personal keys."""

import importlib.util
import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from django.apps import apps

from tests.integration.test_cli_oauth_browser import browser_flow  # noqa: F401
from tests.integration.test_cli_oauth_journey import signed_in_cli  # noqa: F401

HAS_KEY_API = importlib.util.find_spec("model_registry.runtime_keys") is not None
pytestmark = [pytest.mark.optional, pytest.mark.live, pytest.mark.django_db(transaction=True),
              pytest.mark.skipif(not HAS_KEY_API or not apps.is_installed("oauth2_provider"),
                                 reason="Compose the reviewed OAuth issuer and runtime key API")]

if HAS_KEY_API:
    from tests.integration import test_provider_key_validation as validation
    from tests.integration.test_provider_key_validation import provider
else:
    @pytest.fixture
    def provider():
        pytest.skip("Compose the reviewed runtime key API")


@pytest.fixture
def key_cli(signed_in_cli, provider, monkeypatch, tmp_path, capsys):  # noqa: F811
    from model_registry import runtime_keys
    from model_registry.fingerprints import fingerprint
    from model_registry.key_validation import DjangoProviderKeyValidator

    # Host HTTP fixtures keep host ownership; deployment fixtures check UID 65532.
    monkeypatch.setattr("integrations.gateway.keys.os.fchown", lambda *args: None)
    journey = signed_in_cli
    resource = {"id": journey.model_id, "revision": 1,
                "value": {"name": journey.model_id, "provider": "openAI",
                          "params": {"model": "upstream-model", "baseUrl": provider["url"]}}}
    gateway = validation.Gateway(resource)
    journey.flow.domain.catalog.approve(journey.model_id, [], fingerprint(journey.model_id, [resource]),
                                       key_choice="personal")
    monkeypatch.setattr(runtime_keys, "MODEL_GATEWAY", gateway)
    monkeypatch.setattr(runtime_keys, "DjangoProviderKeyValidator",
                        lambda current: DjangoProviderKeyValidator(current, allow_loopback_http=True))
    directory = tmp_path / "provider-keys"
    monkeypatch.setenv("PROVIDER_KEY_DIR", str(directory))
    secrets = [validation.KEY, validation.KEY + "-replacement", journey.credential.access_token,
               journey.credential.refresh_token]

    def key_command(action, value=None, expected=0):
        arguments = ["keeplane", "keys", action, "--profile", str(journey.profile),
                     "--model", journey.model_id]
        if value is not None:
            monkeypatch.setattr("sys.stdin", SimpleNamespace(buffer=io.BytesIO((value + "\n").encode()),
                                                            isatty=lambda: False))
            arguments.append("--key-stdin")
        monkeypatch.setattr("sys.argv", arguments)
        assert journey.cli.main() == expected
        captured = capsys.readouterr()
        assert all(secret not in captured.out + captured.err for secret in secrets)
        return json.loads(captured.out) if expected == 0 else None

    return SimpleNamespace(journey=journey, provider=provider, gateway=gateway,
                           directory=directory, command=key_command, first=secrets[0], second=secrets[1])


def test_browser_credential_adds_replaces_reads_and_removes_provider_key(key_cli, monkeypatch):
    from model_registry.models import DeveloperProviderKey

    flow = key_cli
    assert flow.command("status")["status"] == "missing" and not flow.provider["calls"]
    assert flow.command("set", flow.first) == {"model_id": flow.journey.model_id,
                                              "status": "added", "cleanup_pending": False}
    row = DeveloperProviderKey.objects.get(owner_id=flow.journey.credential.actor_id,
                                          model_id=flow.journey.model_id)
    first_name = row.key_name
    assert (flow.directory / first_name).read_text() == flow.first
    assert (flow.directory / first_name).stat().st_mode & 0o777 == 0o600
    reads = flow.gateway.reads
    assert flow.command("status")["status"] == "added" and flow.gateway.reads == reads
    monkeypatch.setattr(validation, "KEY", flow.second)
    assert flow.command("set", flow.second)["status"] == "added"
    row.refresh_from_db()
    assert row.key_name != first_name and not (flow.directory / first_name).exists()
    assert (flow.directory / row.key_name).read_text() == flow.second
    assert len(flow.provider["calls"]) == 2 and all(call["key_matches"] for call in flow.provider["calls"])
    assert all(call["body"]["max_completion_tokens"] == 1 for call in flow.provider["calls"])
    flow.gateway.resource["revision"] += 1
    assert flow.command("status")["status"] == "added"
    flow.command("set", flow.second, expected=1)
    assert len(flow.provider["calls"]) == 2
    assert flow.command("remove") == {"model_id": flow.journey.model_id,
                                     "status": "missing", "cleanup_pending": False}
    assert not any(flow.directory.iterdir()) and flow.command("status")["status"] == "missing"
    assert "removed" in flow.journey.command("logout")
    assert flow.journey.flow.identity.session(flow.journey.credential.access_token) is None


def test_oauth_logout_after_initial_auth_stops_before_provider_contact(key_cli, monkeypatch):
    from accounts.cli_credentials import RuntimeIdentity
    from model_registry import runtime_keys
    from model_registry.models import DeveloperProviderKey

    original = runtime_keys.key_store

    def withdraw(request, model_id):
        RuntimeIdentity(key_cli.journey.flow.native).logout(request.auth)
        return original(request, model_id)

    monkeypatch.setattr(runtime_keys, "key_store", withdraw)
    key_cli.command("set", key_cli.first, expected=1)
    assert not key_cli.provider["calls"] and not key_cli.directory.exists()
    assert not DeveloperProviderKey.objects.filter(owner_id=key_cli.journey.credential.actor_id).exists()
    assert key_cli.journey.flow.identity.session(key_cli.journey.credential.access_token) is None
    assert key_cli.journey.flow.refresh(key_cli.journey.credential.refresh_token).status_code == 400
    assert (Path(key_cli.journey.profile) / "credential.json").exists()
