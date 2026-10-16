"""Enrollment state ordering; compiled-native acceptance is a separate fixture."""

import json
from copy import deepcopy
from types import SimpleNamespace

import pytest
from integrations.gateway.runtime_config import RuntimeInstallationUnavailable
from model_registry import installed_runtime, runtime_installation
from model_registry.fingerprints import fingerprint
from model_registry.models import ModelApproval

from tests.unit.test_runtime_config import applied


@pytest.fixture
def installation(db, tmp_path, monkeypatch):
    directory = tmp_path / "installed"
    directory.mkdir(mode=0o700)
    base = {
        "config": {},
        "gateways": {"default": {"port": 4000}},
        "llm": {
            "models": [],
            "policies": {
                "apiKey": {
                    "mode": "strict",
                    "keys": [{"keyHash": "sha256:" + "a" * 64}],
                }
            },
        },
    }
    trusted = tmp_path / "trusted.json"
    trusted.write_text(json.dumps(base))
    (directory / "gateway.json").write_bytes(trusted.read_bytes())
    resources = [
        {
            "id": "demo",
            "kind": "llm.model",
            "revision": 1,
            "value": {
                "id": "demo",
                "name": "demo",
                "provider": "openAI",
                "params": {"model": "fixture"},
            },
        }
    ]
    ModelApproval.objects.create(
        model_id="demo",
        key_choice="none",
        gateway_fingerprint=fingerprint("demo", resources),
    )
    dump = applied()
    dump.update(
        workloads=[],
        services=[],
        binds=[],
        routes={},
        policies=[],
        version={},
        config={},
    )
    f = SimpleNamespace(
        directory=directory,
        resources=resources,
        dump=dump,
        requests=[],
        barriers=[],
        fault=None,
    )
    f.read_file = lambda: json.loads((directory / "gateway.json").read_text())

    def request(path, *, timeout, connection_retries):
        assert timeout == 5 and connection_retries == 0
        f.requests.append(path)
        file = f.read_file()
        if path == "/api/config":
            return 200, file
        if path == "/api/config/effective":
            file["llm"]["models"].extend(deepcopy([row["value"] for row in resources]))
            return 200, file
        return 200, {"resources": deepcopy(resources)}

    f.gateway = SimpleNamespace(base_url="http://127.0.0.1:4000", request=request)

    def barrier(*args):
        assert json.loads((directory / "manifest.json").read_text())["enabled"] is False
        f.barriers.append(True)
        if f.fault:
            f.fault()

    monkeypatch.setattr(runtime_installation, "require_applied_overlay", barrier)
    monkeypatch.setattr(
        runtime_installation, "require_applied_models", lambda *args: None
    )
    monkeypatch.setattr(
        installed_runtime, "read_applied", lambda gateway: deepcopy(dump)
    )
    f.service = runtime_installation.DjangoRuntimeInstallation(
        f.gateway,
        directory,
        trusted,
        str(directory),
        read_applied=lambda: deepcopy(dump),
    )
    return f


def disabled(f):
    assert json.loads((f.directory / "manifest.json").read_text()) == {
        "version": 2,
        "enabled": False,
    }


def test_manifest_enabled_only_after_applied_and_fresh_gates(installation):
    f = installation
    assert f.service.install(["demo"]) == {"models": ["demo"]}
    value = installed_runtime.manifest(f.directory / "manifest.json")
    assert f.barriers and value["models"]["demo"]["fingerprint"] == fingerprint(
        "demo", f.resources
    )
    assert value["file_digest"] == installed_runtime.digest(f.read_file())
    assert all(path.startswith("/api/config") for path in f.requests)
    assert (f.directory / "manifest.json").stat().st_mode & 0o077 == 0


@pytest.mark.parametrize("fault", ["approval", "definition", "applied", "key"])
def test_change_during_publication_leaves_disabled_config_for_inspection(
    installation, monkeypatch, fault
):
    f = installation
    if fault == "key":
        name = "key-" + "b" * 32
        key = f.directory / name
        key.write_text("synthetic-provider-value")
        key.chmod(0o600)
        f.resources[0]["value"]["auth"] = {"key": {"value": {"file": str(key)}}}
        ModelApproval.objects.filter(pk="demo").update(
            key_choice="shared", gateway_fingerprint=fingerprint("demo", f.resources)
        )
        f.fault = key.unlink
    elif fault == "approval":
        f.fault = lambda: ModelApproval.objects.filter(pk="demo").delete()
    elif fault == "definition":
        f.fault = lambda: f.resources[0].update(revision=2)
    else:

        def fail():
            raise RuntimeInstallationUnavailable("Native application failed")

        f.fault = fail
        ticks = iter([0, 16])
        monkeypatch.setattr(
            runtime_installation, "time", SimpleNamespace(monotonic=lambda: next(ticks))
        )
    with pytest.raises(
        (RuntimeInstallationUnavailable, installed_runtime.ModelPolicyUnavailable)
    ):
        f.service.install(["demo"])
    disabled(f)
    assert "binds" in f.read_file()  # Do not roll back an unknown/partial publication.


@pytest.mark.parametrize(
    "fault", ["personal", "legacy", "missing-key", "existing-mode", "changed-base"]
)
def test_unsupported_preflight_never_publishes(installation, fault):
    f = installation
    before = (f.directory / "gateway.json").read_bytes()
    if fault == "personal":
        ModelApproval.objects.filter(pk="demo").update(key_choice="personal")
    elif fault == "legacy":
        del f.resources[0]["value"]["id"]
        ModelApproval.objects.filter(pk="demo").update(
            gateway_fingerprint=fingerprint("demo", f.resources)
        )
    elif fault == "missing-key":
        f.resources[0]["value"]["auth"] = {
            "key": {"value": {"file": str(f.directory / ("key-" + "b" * 32))}}
        }
        ModelApproval.objects.filter(pk="demo").update(
            key_choice="shared", gateway_fingerprint=fingerprint("demo", f.resources)
        )
    elif fault == "existing-mode":
        f.service.gateway_mode = "existing"
    else:
        f.service.trusted_file.write_text("changed")
    with pytest.raises(
        (RuntimeInstallationUnavailable, installed_runtime.ModelPolicyUnavailable)
    ):
        f.service.install(["demo"])
    assert (f.directory / "gateway.json").read_bytes() == before and not f.barriers
    if fault != "existing-mode":
        disabled(f)


def test_a_second_enrollment_requires_a_fresh_base(installation):
    f = installation
    f.service.install(["demo"])
    with pytest.raises(RuntimeInstallationUnavailable, match="fresh"):
        f.service.install(["demo"])
    disabled(f)


def test_loaded_base_must_match_trusted_disk_bytes(installation):
    f = installation
    original = f.gateway.request

    def changed(path, **kwargs):
        status, body = original(path, **kwargs)
        if path == "/api/config":
            body["config"]["unknownPolicy"] = {"enabled": True}
        return status, body

    f.gateway.request = changed
    before = (f.directory / "gateway.json").read_bytes()
    with pytest.raises(RuntimeInstallationUnavailable, match="loaded base"):
        f.service.install(["demo"])
    assert (f.directory / "gateway.json").read_bytes() == before and not f.barriers
    disabled(f)


@pytest.mark.parametrize("disable_fails", [False, True])
def test_post_replace_failure_attempts_disable_and_never_claims_ready(
    installation, monkeypatch, disable_fails
):
    f = installation
    original = runtime_installation.atomic_private
    published = False
    attempts = []

    def failing(path, value):
        nonlocal published
        if path.name == "manifest.json":
            attempts.append(value["enabled"])
            if published and disable_fails:
                raise OSError("Synthetic disabled-file failure")
        original(path, value)
        if path.name == "manifest.json" and value["enabled"]:
            published = True
            raise OSError("Synthetic directory fsync failure after replacement")

    monkeypatch.setattr(runtime_installation, "atomic_private", failing)
    with pytest.raises(RuntimeInstallationUnavailable, match="could not be confirmed"):
        f.service.install(["demo"])
    assert attempts == [False, True, False]
    if not disable_fails:
        disabled(f)
    else:
        assert (
            json.loads((f.directory / "manifest.json").read_text())["enabled"] is True
        )
    assert not (f.directory / "candidate.json").exists()
