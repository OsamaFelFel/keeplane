"""The private model enroller re-enrols a running managed gateway (ADR 027).

The gateway here is a fake that loads the private guard file when its applied
state is read, the way the native gateway watches its file. Native acceptance
on the real gateway image is a separate, live check.
"""

import json
import os
import sqlite3
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from integrations.gateway.runtime_config import RuntimeInstallationUnavailable
from model_registry import installed_runtime, model_enroller, runtime_installation
from model_registry.fingerprints import fingerprint
from model_registry.installed_runtime import ModelPolicyUnavailable, digest
from model_registry.models import ModelApproval

BASE = {
    "config": {},
    "gateways": {"default": {"port": 4000}},
    "llm": {
        "models": [],
        "policies": {
            "apiKey": {"mode": "strict", "keys": [{"keyHash": "sha256:" + "a" * 64}]}
        },
    },
}


def model(identifier, revision=1, base_url=None):
    params = {"model": "fixture"}
    if base_url:
        params["baseUrl"] = base_url
    return {
        "id": identifier,
        "kind": "llm.model",
        "revision": revision,
        "value": {
            "id": identifier,
            "name": identifier,
            "provider": "openAI",
            "params": params,
        },
    }


def approve(identifier, resources, key_choice="none"):
    ModelApproval.objects.update_or_create(
        model_id=identifier,
        defaults={
            "key_choice": key_choice,
            "gateway_fingerprint": fingerprint(identifier, resources),
        },
    )


def selected_fingerprints(config):
    """The definition fingerprint each model's final check carries."""
    result = {}
    for row in config.get("policies", []):
        callback = row["policy"].get("extAuthz")
        if not callback:
            continue
        target = row["target"]["backend"]["backend"]["name"]
        body = callback["protocol"]["http"]["body"]
        result[target.rsplit(":", 1)[1]] = body.split('"definition_fingerprint": "')[1][
            :64
        ]
    return result


@pytest.fixture
def gateway(db, tmp_path, monkeypatch):
    directory = tmp_path / "installed"
    directory.mkdir(mode=0o700)
    trusted = directory / "trusted.json"
    raw = json.dumps(BASE, sort_keys=True, separators=(",", ":")).encode()
    trusted.write_bytes(raw)
    (directory / "gateway.json").write_bytes(raw)
    (directory / "manifest.json").write_text('{"version":2,"enabled":false}')
    resources = [model("demo")]
    approve("demo", resources)
    f = SimpleNamespace(
        directory=directory,
        resources=resources,
        loaded=deepcopy(BASE),
        apply=True,
        swaps=[],
        writes=[],
        during=None,
    )
    f.file = lambda: json.loads((directory / "gateway.json").read_text())

    def dump():
        # The native gateway applies its watched file; the fake does so on read.
        if f.apply:
            f.loaded = f.file()
        return {
            "workloads": [],
            "services": [],
            "binds": [
                {"key": f"bind/{row['port']}"} for row in f.loaded.get("binds", [])
            ],
            "routes": {},
            "policies": [],
            "backends": [
                {
                    "backend": {
                        "llmRouter": {
                            "name": "llm:router",
                            "namespace": "",
                            "target": {
                                "models": [
                                    {
                                        "name": row["id"],
                                        "backend": {
                                            "backend": "/llm:model:" + row["id"]
                                        },
                                        "headerMatches": [],
                                    }
                                    for row in f.resources
                                ],
                                "virtualModels": [],
                            },
                        }
                    }
                }
            ],
            "models": [],
            "version": {"file": digest(f.loaded)},
            "config": {},
        }

    def request(path, *, timeout, connection_retries):
        assert connection_retries == 0
        if path == "/api/config":
            return 200, deepcopy(f.loaded)
        if path == "/api/config/effective":
            value = deepcopy(f.loaded)
            value["llm"]["models"].extend(deepcopy([r["value"] for r in f.resources]))
            return 200, value
        return 200, {"resources": deepcopy(f.resources)}

    def readback(applied, generated, models, targets):
        if applied["version"]["file"] != digest(generated):
            raise RuntimeInstallationUnavailable("Not applied yet")
        # Nothing may be served while the guard moves.
        assert json.loads((directory / "manifest.json").read_text()) == {
            "version": 2,
            "enabled": False,
        }
        f.swaps.append(selected_fingerprints(generated))
        if f.during:
            f.during()

    original = runtime_installation.atomic_private

    def recording(path, value):
        f.writes.append(path.name)
        original(path, value)

    for module in (runtime_installation, model_enroller):
        monkeypatch.setattr(module, "atomic_private", recording)
    monkeypatch.setattr(runtime_installation, "require_applied_overlay", readback)
    monkeypatch.setattr(
        runtime_installation, "require_applied_models", lambda *args: None
    )
    monkeypatch.setattr(installed_runtime, "read_applied", lambda gateway: dump())
    f.gateway = SimpleNamespace(base_url="http://127.0.0.1:4000", request=request)
    f.gate = installed_runtime.DjangoInstalledRuntimeGate(
        f.gateway, str(directory / "manifest.json"), str(directory)
    )
    f.enroller = model_enroller.DjangoModelEnroller(
        runtime_installation.DjangoRuntimeInstallation(
            f.gateway, directory, trusted, str(directory), read_applied=dump
        ),
        deadline=0.5,
        sleep=lambda seconds: None,
        now=lambda: f.clock,
    )
    f.clock = 1000.0
    return f


def declaration(f):
    return json.loads((f.directory / "manifest.json").read_text())


def held(f):
    """A change that alters a served guard waits; nothing else is written."""
    guard = (f.directory / "gateway.json").read_bytes(), declaration(f)
    assert f.enroller.reconcile() == model_enroller.Enrolment("held", ())
    f.clock += model_enroller.HOLD_SECONDS - 1
    assert f.enroller.reconcile() == model_enroller.Enrolment("held", ())
    assert ((f.directory / "gateway.json").read_bytes(), declaration(f)) == guard
    f.clock += 1


def test_the_hold_outlasts_every_retry_of_a_request():
    # Three attempts, each up to 60 seconds to the provider's headers.
    assert model_enroller.HOLD_SECONDS > 3 * 60 + 1


def test_enrols_a_running_gateway_from_saved_approvals(gateway):
    f = gateway
    result = f.enroller.reconcile()
    assert result == model_enroller.Enrolment("enrolled", ("demo",))
    assert set(declaration(f)["models"]) == {"demo"}
    assert f.gate.require_installed("demo")["fingerprint"] == fingerprint(
        "demo", f.resources
    )
    assert (f.directory / "manifest.json").stat().st_mode & 0o077 == 0


def test_a_second_run_with_nothing_changed_writes_nothing(gateway):
    f = gateway
    f.enroller.reconcile()
    before = (f.directory / "gateway.json").read_bytes(), declaration(f)
    f.writes.clear()
    assert f.enroller.reconcile().state == "unchanged"
    assert f.writes == []
    assert ((f.directory / "gateway.json").read_bytes(), declaration(f)) == before


def test_adding_a_model_keeps_serving_the_others_without_a_restart(gateway):
    f = gateway
    f.enroller.reconcile()
    f.resources.append(model("second"))
    approve("second", f.resources)
    # A new store entry changes the gateway's effective state: the old guard
    # is refused until the enroller confirms the new one.
    with pytest.raises(ModelPolicyUnavailable):
        f.gate.require_installed("demo")
    assert f.enroller.reconcile() == model_enroller.Enrolment(
        "enrolled", ("demo", "second")
    )
    assert f.gate.require_installed("demo") and f.gate.require_installed("second")


def test_a_removed_model_is_dropped_and_the_protected_port_closes(gateway):
    f = gateway
    f.enroller.reconcile()
    ModelApproval.objects.filter(pk="demo").delete()
    f.resources.clear()
    held(f)
    assert f.enroller.reconcile() == model_enroller.Enrolment("withdrawn", ())
    assert declaration(f) == {"version": 2, "enabled": False}
    assert f.file() == BASE and "binds" not in f.loaded
    assert f.enroller.reconcile().state == "unchanged"


def test_withdrawing_one_of_two_models_keeps_the_other(gateway):
    f = gateway
    f.resources.append(model("second"))
    approve("second", f.resources)
    f.enroller.reconcile()
    ModelApproval.objects.filter(pk="second").delete()
    # The removal is refused as soon as the app saves it.
    with pytest.raises(ModelPolicyUnavailable):
        f.gate.require_installed("second")
    del f.resources[1]
    held(f)
    assert f.enroller.reconcile().models == ("demo",)
    with pytest.raises(installed_runtime.ModelAccessDenied):
        f.gate.require_installed("second")
    assert f.gate.require_installed("demo")


@pytest.mark.parametrize("fault", ["stale-approval", "unsupported", "missing-key"])
def test_a_model_that_cannot_be_enrolled_is_left_out_alone(gateway, fault):
    f = gateway
    f.resources.append(model("second"))
    approve("second", f.resources)
    if fault == "stale-approval":
        # The gateway moved on but no saved approval matches it yet.
        f.resources[1]["revision"] = 2
    elif fault == "unsupported":
        f.resources[1]["value"]["provider"] = "bedrock"
        approve("second", f.resources)
    else:
        key = str(f.directory / ("key-" + "c" * 32))
        f.resources[1]["value"]["auth"] = {"key": {"value": {"file": key}}}
        approve("second", f.resources, key_choice="shared")
    assert f.enroller.reconcile().models == ("demo",)
    with pytest.raises(installed_runtime.ModelAccessDenied):
        f.gate.require_installed("second")


def test_a_guard_that_never_reads_back_leaves_everything_refused(gateway, monkeypatch):
    f = gateway
    f.enroller.reconcile()
    f.resources.append(model("second"))
    approve("second", f.resources)
    f.apply = False  # The gateway never loads the new file.
    ticks = iter([0, 16])
    monkeypatch.setattr(
        runtime_installation,
        "time",
        SimpleNamespace(monotonic=lambda: next(ticks), sleep=lambda seconds: None),
    )
    with pytest.raises(RuntimeInstallationUnavailable):
        f.enroller.reconcile()
    assert declaration(f) == {"version": 2, "enabled": False}
    with pytest.raises(ModelPolicyUnavailable):
        f.gate.require_installed("demo")


def test_an_approval_change_during_enrolment_is_not_enabled(gateway):
    f = gateway
    f.during = lambda: ModelApproval.objects.filter(pk="demo").delete()
    with pytest.raises(ModelPolicyUnavailable):
        f.enroller.reconcile()
    assert declaration(f) == {"version": 2, "enabled": False}


def test_a_request_in_flight_cannot_pair_an_old_destination_with_a_new_approval(
    gateway,
):
    f = gateway
    f.enroller.reconcile()
    old = fingerprint("demo", f.resources)
    # An admin points the model at a new destination; the app saves the new
    # approval once every copy reads the new definition back (#179).
    f.resources[0] = model("demo", revision=2, base_url="https://new.example")
    approve("demo", f.resources)
    new = fingerprint("demo", f.resources)
    assert old != new
    # A request that entered under the old guard still carries the old
    # destination's fingerprint into its final check: refused before, during
    # and after the guard moves.
    with pytest.raises(ModelPolicyUnavailable):
        f.gate.require_installed("demo", old)
    # The old guard stays in place, refusing both, until any request that kept
    # the old destination has passed its last final check. Only then can a
    # final check that carries the new fingerprint be reached at all.
    for supplied in (old, new):
        with pytest.raises(ModelPolicyUnavailable):
            f.gate.require_installed("demo", supplied)
    assert old in (f.directory / "gateway.json").read_text()
    held(f)
    seen = []

    def in_flight():
        for supplied in (old, new):
            try:
                f.gate.require_installed("demo", supplied)
            except ModelPolicyUnavailable:
                seen.append(supplied)

    f.during = in_flight
    f.enroller.reconcile()
    assert seen == [old, new]  # Nothing is served while the guard moves.
    assert f.swaps[-1] == {"demo": new}
    with pytest.raises(ModelPolicyUnavailable):
        f.gate.require_installed("demo", old)
    assert f.gate.require_installed("demo", new)["fingerprint"] == new
    assert old not in (f.directory / "gateway.json").read_text()


def test_a_further_change_during_the_hold_starts_it_again(gateway):
    f = gateway
    f.enroller.reconcile()
    f.resources[0] = model("demo", revision=2)
    approve("demo", f.resources)
    assert f.enroller.reconcile().state == "held"
    f.clock += model_enroller.HOLD_SECONDS - 5
    f.resources[0] = model("demo", revision=3)
    approve("demo", f.resources)
    assert f.enroller.reconcile().state == "held"
    f.clock += 10
    assert f.enroller.reconcile().state == "held"
    f.clock += model_enroller.HOLD_SECONDS
    assert f.enroller.reconcile().state == "enrolled"
    assert json.loads((f.directory / "served.json").read_text()) == {
        "served": {"demo": fingerprint("demo", f.resources)},
        "pending": None,
    }


@pytest.mark.parametrize("record", ["missing-after-install", "unreadable"])
def test_the_served_record_is_never_guessed(gateway, record):
    f = gateway
    f.enroller.reconcile()
    path = f.directory / "served.json"
    if record == "unreadable":
        path.write_text("{")
        f.resources.append(model("second"))
        approve("second", f.resources)
        # Which guards are served is unknown, so even an add waits.
        assert f.enroller.reconcile().state == "held"
        f.clock += model_enroller.HOLD_SECONDS
        assert f.enroller.reconcile().models == ("demo", "second")
    else:
        # An operator installation leaves no record; the enabled declaration
        # shows what is served, and an unchanged guard is kept.
        path.unlink()
        f.writes.clear()
        assert f.enroller.reconcile().state == "unchanged"
        assert f.writes == ["served.json"]


def test_only_the_managed_loopback_gateway_is_enrolled(gateway):
    f = gateway
    f.enroller.installation.gateway_mode = "existing"
    with pytest.raises(RuntimeInstallationUnavailable):
        f.enroller.reconcile()
    assert f.writes == []


def test_the_command_refuses_an_unconfigured_volume(db, settings):
    settings.RUNTIME_GUARD_MANIFEST_FILE = "/elsewhere/manifest.json"
    with pytest.raises(CommandError, match="private managed installation volume"):
        call_command("run_model_enroller", "--once")


def test_the_command_reports_failure_without_details(db, settings, monkeypatch):
    settings.RUNTIME_GUARD_MANIFEST_FILE = "/installed/manifest.json"
    settings.RUNTIME_AUTHORIZER_KEY_FILE = "/installed/callback-key"

    def unavailable(self):
        raise RuntimeInstallationUnavailable("synthetic detail")

    monkeypatch.setattr(model_enroller.DjangoModelEnroller, "reconcile", unavailable)
    with pytest.raises(CommandError) as error:
        call_command("run_model_enroller", "--once")
    assert "synthetic" not in str(error.value)
    assert "stays refused" in str(error.value)


PROBE = """
import django
from django.db import connection

django.setup()
with connection.cursor() as cursor:
    cursor.execute("SELECT count(*) FROM approvals")
    print(cursor.fetchone()[0])
    try:
        cursor.execute("INSERT INTO approvals VALUES ('widened')")
    except Exception as error:
        print(type(error).__name__)
"""


def test_the_enroller_database_connection_cannot_write(tmp_path):
    database = tmp_path / "keeplane.sqlite3"
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE approvals (model_id TEXT)")
    connection.execute("INSERT INTO approvals VALUES ('demo')")
    connection.commit()
    connection.close()
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("KEEPLANE_DATABASE", "DJANGO_"))
    }
    environment.update(
        DJANGO_SETTINGS_MODULE="config.settings",
        KEEPLANE_SQLITE_PATH=str(database),
        KEEPLANE_DATABASE_READ_ONLY="1",
        PYTHONPATH=str(
            Path(__file__).resolve().parents[2] / "components/control-plane"
        ),
    )
    result = subprocess.run(
        [sys.executable, "-c", PROBE],
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    assert result.stdout.split() == ["1", "OperationalError"]
    connection = sqlite3.connect(database)
    try:
        assert connection.execute("SELECT count(*) FROM approvals").fetchone() == (1,)
    finally:
        connection.close()
