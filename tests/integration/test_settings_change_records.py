"""Settings-change Audit records for every admin change to a model or data class.

Spec 006 ST21. The plain-English cases are in settings-change-record-cases.md.
"""

import json
import select
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from django.test import Client

from model_registry import registration
from model_registry.registration import ModelManagement
from tests.integration import test_audit_persistence as persistence
from audit.models import AuditRecord
from django.db import OperationalError
from tests.unit.test_model_registration_ids import Gateway

# Reuse the separate-process SQLite and PostgreSQL harness.
database = persistence.database
start_process = persistence.start_process

OPTIONAL = ("settings", "held_requests", "model_answers")

EVERY_CHANGE = [
    "Turned data classes on; added starter classes: Public, Internal, Confidential",
    "Set up model alpha; provider key: shared; approved classes: Public",
    "Changed model alpha: approved classes: Public to Public, Internal",
    "Changed model alpha: replaced the shared provider key",
    "Changed model alpha: provider key: shared to personal",
    "Set up model beta; provider key: none; approved classes: none",
    "Changed model beta: approved its changed gateway definition",
    "Added data class Finance; approved models: alpha",
    "Changed data class Finance: renamed to Finance team; approved models: alpha to none",
    "Changed data class Finance team: approved models: none to alpha, beta",
    "Removed data class Finance team; it was approved for models: alpha, beta",
    "Removed model beta from the gateway",
    "Removed Keeplane setup for model alpha",
    "Turned data classes off",
]


def settings_records(process):
    rows, page = [], 1
    while True:
        result = process.records(kind="settings", page=page, page_size=50)
        rows += result["records"]
        if not result["has_more"]:
            return list(reversed(rows))
        page += 1


def test_sc_01_after_install_changes_are_not_recorded(start_process):
    app = start_process()
    app.ask("migrate")
    assert app.ask("options") == dict.fromkeys(OPTIONAL, False)
    app.ask("settings_changes")
    app.ask("sign_in", count=1)
    everything = app.records(page=1, page_size=50)
    assert [row["kind"] for row in everything["records"]] == ["break_glass_sign_ins"]


def test_sc_02_every_model_and_class_change_names_who_what_and_when(start_process):
    app = start_process()
    app.ask("migrate")
    app.ask("audit_option", kind="settings", enabled=True)
    app.ask("settings_changes")
    rows = settings_records(app)
    assert [row["what"] for row in rows] == EVERY_CHANGE
    assert {row["who"] for row in rows} == {"settings-admin"}
    assert {row["kind"] for row in rows} == {"settings"}
    assert all(row["when"].endswith("+00:00") for row in rows)
    assert [row["id"] for row in rows] == sorted(row["id"] for row in rows)
    # A second app process on the same database sees the same records.
    assert settings_records(start_process()) == rows


def test_sc_03_one_kind_on_leaves_the_others_off(start_process):
    app = start_process()
    app.ask("migrate")
    assert app.ask("audit_option", kind="settings", enabled=True) == {
        "settings": True,
        "held_requests": False,
        "model_answers": False,
    }
    app.ask("audit_option", kind="settings", enabled=False)
    assert app.ask("audit_option", kind="held_requests", enabled=True) == {
        "settings": False,
        "held_requests": True,
        "model_answers": False,
    }
    app.ask("audit_option", kind="held_requests", enabled=False)
    assert app.ask("audit_option", kind="model_answers", enabled=True) == {
        "settings": False,
        "held_requests": False,
        "model_answers": True,
    }
    app.ask("settings_changes")
    assert app.records()["total"] == 0


def test_sc_05_a_refused_change_leaves_no_record(start_process):
    app = start_process()
    app.ask("migrate")
    app.ask("audit_option", kind="settings", enabled=True)
    result = app.ask("refused_changes")
    assert result["refused"] == [
        "DataClassError",
        "DataClassError",
        "DataClassError",
        "DataClassError",
        "DataClassError",
        "DataClassError",
        "DataClassError",
        "ValueError",
        "ValueError",
        "ValueError",
    ]
    assert result["removed_missing"] is False
    assert result["before"] == result["after"]
    assert result["after"]["records"] == 2


def test_sc_06_a_failed_record_write_keeps_the_change_out(start_process):
    app = start_process()
    app.ask("migrate")
    app.ask("audit_option", kind="settings", enabled=True)
    result = app.ask("failed_record_writes")
    assert set(result["outcome"].values()) == {"StorageUnavailable"}
    assert len(result["outcome"]) == 9
    assert result["before"] == result["after"]
    assert result["after"]["classes_enabled"] is True


def test_sc_11_a_removal_that_cannot_finish_changes_nothing(start_process):
    app = start_process()
    app.ask("migrate")
    result = app.ask("removal_rollbacks")
    unchanged = {"in_gateway": True, "approved": True, "pinned_to_gateway": True}

    failed = result["record write fails"]
    assert failed["status"] == 503 and failed["error"] == "StorageUnavailable"
    assert {key: failed[key] for key in unchanged} == unchanged

    refused = result["gateway refuses"]
    assert (refused["status"], refused["error"]) == (503, "Gateway unavailable")
    assert {key: refused[key] for key in unchanged} == unchanged

    restored = result["commit fails"]
    assert restored["status"] == 503
    assert restored["error"] == (
        "Keeplane couldn't record the removal. "
        "The model is back in the gateway and nothing changed."
    )
    assert {key: restored[key] for key in unchanged} == unchanged

    landed = result["commit lands but reports failure"]
    assert (landed["status"], landed["in_gateway"], landed["approved"]) == (
        200,
        False,
        False,
    )

    outside_failed = result["outside, record write fails"]
    assert outside_failed["status"] == 503
    assert {key: outside_failed[key] for key in unchanged} == unchanged
    outside = result["outside"]
    assert (outside["status"], outside["in_gateway"], outside["approved"]) == (
        200,
        True,
        False,
    )

    normal = result["normal"]
    assert (normal["status"], normal["in_gateway"], normal["approved"]) == (
        200,
        False,
        False,
    )
    # The outside model is never sent to the gateway for deletion.
    assert "outside" not in result["gateway deletes"]
    assert result["records"] == [
        "Removed model commit-lands from the gateway",
        "Removed Keeplane setup for model outside",
        "Removed model normal from the gateway",
    ]


# The cases below run in the test process on SQLite.


class FlakyGateway(Gateway):
    """A gateway whose model check fails a set number of times for one model."""

    def __init__(self):
        super().__init__()
        self.refuse = {}

    def request(self, path, body=None, method=None, **options):
        if path == "/v1/chat/completions" and self.refuse.get(body["model"]):
            self.refuse[body["model"]] -= 1
            return 500, {"error": "synthetic provider failure"}
        return super().request(path, body, method, **options)


ADMIN = ("admin-id", "first-admin")
ORIGINAL_KEY = "synthetic-original-provider-key-4f1c"
REPLACEMENT_KEY = "synthetic-replacement-provider-key-9d2e"


@pytest.fixture
def management(domain_services, tmp_path, monkeypatch):
    saved = []

    def save(directory, value):
        path = Path(directory) / f"key-{len(saved)}"
        path.parent.mkdir(exist_ok=True)
        path.write_text(value)
        path.chmod(0o600)
        saved.append(str(path))
        return str(path)

    monkeypatch.setattr(registration, "save_provider_key", save)
    # Key file ownership has its own cases; these cases check what Audit keeps.
    monkeypatch.setattr(registration, "managed_provider_key", lambda *_: True)
    monkeypatch.setattr(
        registration,
        "remove_provider_key",
        lambda _directory, path: Path(path).unlink() is None,
    )
    domain_services.classes.set_enabled(True)
    result = ModelManagement(
        domain_services.catalog,
        domain_services.classes,
        FlakyGateway(),
        ADMIN,
        "managed",
        None,
        str(tmp_path / "keys"),
        set(),
        {"openai": "http://provider.invalid/v1", "anthropic": ""},
        "",
    )
    result.saved_key_files = saved
    return domain_services, result


def test_sc_04_model_records_never_hold_keys_passwords_or_prompts(management):
    services, models = management
    services.audit.set_option("settings", True)
    status, _ = models.add(
        {
            "name": "cloud-model",
            "model": "upstream",
            "source": "openai",
            "key_choice": "shared",
            "shared_key": ORIGINAL_KEY,
            "approved_classes": ["Public"],
        }
    )
    assert status == 200
    status, _ = models.setup(
        "cloud-model",
        {
            "key_choice": "shared",
            "approved_classes": ["Public", "Internal"],
            "replace_shared_key": REPLACEMENT_KEY,
        },
    )
    assert status == 200, _
    status, _ = models.setup(
        "cloud-model", {"key_choice": "shared", "approved_classes": ["Internal"]}
    )
    assert status == 200
    services.catalog.remove("cloud-model", ADMIN)

    records = services.audit.records(kind="settings")["records"]
    assert [row["what"] for row in reversed(records)] == [
        "Set up model cloud-model; provider key: shared; approved classes: Public",
        "Changed model cloud-model: replaced the shared provider key; "
        "approved classes: Public to Public, Internal",
        "Changed model cloud-model: approved classes: Public, Internal to Internal",
        "Removed Keeplane setup for model cloud-model",
    ]
    forbidden = [
        ORIGINAL_KEY,
        REPLACEMENT_KEY,
        "first-test-password-123",
        "Reply OK",
        *models.saved_key_files,
        *(Path(item).name for item in models.saved_key_files),
    ]
    text = " ".join(row["what"] + " " + row["who"] for row in records)
    assert not [item for item in forbidden if item in text]


def test_sc_07_admin_screens_record_class_changes_through_the_api(domain_services):
    services = domain_services
    client = Client()
    with (
        patch("common.api.IDENTITY", services.identity),
        patch("audit.views.AUDIT", services.audit),
        patch("data_classes.views.DATA_CLASSES", services.classes),
    ):
        client.cookies["keeplane_session"] = services.identity.login(
            "first-admin", "first-test-password-123"
        )

        def call(method, path, body=None):
            response = getattr(client, method)(
                path,
                body or {},
                content_type="application/json",
                HTTP_X_KEEPLANE_ACTION="1",
            )
            assert response.status_code in (200, 201), response.content
            return response.json()

        call("put", "/api/audit/options/settings", {"enabled": True})
        call("put", "/api/data-classes/mode", {"enabled": True})
        added = call(
            "post", "/api/data-classes", {"name": "Legal", "approved_model_ids": []}
        )
        call(
            "put",
            f"/api/data-classes/{added['id']}",
            {"name": "Legal team", "approved_model_ids": []},
        )
        call("delete", f"/api/data-classes/{added['id']}")
        call("put", "/api/data-classes/mode", {"enabled": False})
        shown = client.get("/api/audit/records?kind=settings").json()

    assert [row["what"] for row in reversed(shown["records"])] == [
        "Turned data classes on; added starter classes: Public, Internal, Confidential",
        "Added data class Legal; approved models: none",
        "Changed data class Legal: renamed to Legal team",
        "Removed data class Legal team; it was approved for models: none",
        "Turned data classes off",
    ]
    assert {row["who"] for row in shown["records"]} == {"first-admin"}
    assert "first-test-password-123" not in str(shown)


def add_shared_cloud_model(models):
    return models.add(
        {
            "name": "cloud-model",
            "model": "upstream",
            "source": "openai",
            "key_choice": "shared",
            "shared_key": ORIGINAL_KEY,
            "approved_classes": ["Public"],
        }
    )


def replace_key(models):
    return models.setup(
        "cloud-model",
        {
            "key_choice": "shared",
            "approved_classes": ["Public", "Internal"],
            "replace_shared_key": REPLACEMENT_KEY,
        },
    )


def test_sc_08_a_failed_key_replacement_writes_no_record(management):
    services, models = management
    services.audit.set_option("settings", True)
    assert add_shared_cloud_model(models)[0] == 200
    original = models.gateway.records["cloud-model"]["value"]
    models.gateway.refuse["cloud-model"] = 1
    status, body = replace_key(models)
    assert status == 503
    assert body["error"].endswith("The previous key is still active.")
    assert models.gateway.records["cloud-model"]["value"] == original
    approval = services.catalog.get("cloud-model")
    assert approval["approved_classes"] == ["Public"]
    assert [row["what"] for row in services.audit.records()["records"]] == [
        "Set up model cloud-model; provider key: shared; approved classes: Public"
    ]


def test_sc_09_a_failed_record_write_undoes_the_gateway_step(management):
    services, models = management
    services.audit.set_option("settings", True)
    assert add_shared_cloud_model(models)[0] == 200
    original = models.gateway.records["cloud-model"]["value"]
    before = services.audit.records()["total"]
    failing = patch.object(
        AuditRecord.objects, "create", side_effect=OperationalError("audit down")
    )

    with failing:
        status, body = replace_key(models)
    assert status == 503 and "previous key is still active" in body["error"]
    assert models.gateway.records["cloud-model"]["value"] == original
    assert services.catalog.get("cloud-model")["approved_classes"] == ["Public"]

    with failing:
        status, _ = models.add(
            {"name": "local-model", "model": "upstream", "source": "fixture"}
        )
    assert status == 503
    assert "local-model" not in models.gateway.records
    assert services.catalog.get("local-model") is None

    with failing:
        status, _ = models.add(
            {
                "name": "second-cloud",
                "model": "second-upstream",
                "source": "openai",
                "key_choice": "shared",
                "shared_key": REPLACEMENT_KEY,
            }
        )
    assert status == 503
    assert "second-cloud" not in models.gateway.records
    assert services.catalog.get("second-cloud") is None
    assert services.audit.records()["total"] == before
    assert all(not Path(path).exists() for path in models.saved_key_files[1:])


def test_sc_10_a_change_of_owner_is_named(domain_services):
    services = domain_services
    services.classes.set_enabled(True)
    services.audit.set_option("settings", True)
    services.catalog.approve("gateway-model", [], "c" * 64, ADMIN)
    services.catalog.approve(
        "gateway-model", [], "c" * 64, ADMIN, owned_by_keeplane=True
    )
    services.catalog.approve("gateway-model", [], "d" * 64, ADMIN)
    assert [row["what"] for row in services.audit.records()["records"]] == [
        "Changed model gateway-model: approved its changed gateway definition; "
        "no longer set up by Keeplane",
        "Changed model gateway-model: now set up by Keeplane",
        "Set up model gateway-model; provider key: none; approved classes: none",
    ]


LEVEL_RECORDS = [
    "Changed complexity pick Complex: Keeplane's pick to model alpha",
    "Changed complexity pick Complex: model alpha to model beta",
    "Changed complexity pick Complex: model beta to Keeplane's pick",
]


def test_sc_12_complexity_pick_records_commit_with_the_change(start_process):
    app = start_process()
    app.ask("migrate")
    assert app.ask("level_setup")["records"] == []
    result = app.ask("level_changes")
    assert result["refused"] == ["Complex"]
    assert result["records"] == LEVEL_RECORDS
    assert result["choices"] == {}
    assert result["models"] == ["alpha", "beta"]
    rows = settings_records(start_process())
    assert [row["what"] for row in rows] == LEVEL_RECORDS
    assert {row["who"] for row in rows} == {"settings-admin"}


def send(process, **command):
    """Send one command without waiting for its answer."""
    process.child.stdin.write(json.dumps(command) + "\n")
    process.child.stdin.flush()


def answer(process, timeout):
    """The process's next answer, or None if it doesn't answer in time."""
    ready, _, _ = select.select([process.child.stdout], [], [], timeout)
    if not ready:
        return None
    reply = json.loads(process.child.stdout.readline())
    assert reply["ok"], reply.get("error")
    return reply["result"]


def wait_until(path, timeout=30):
    deadline = time.monotonic() + timeout
    while not path.exists():
        assert time.monotonic() < deadline, "The first step never took the lock"
        time.sleep(0.05)


@pytest.mark.parametrize("first", ["remove", "change_level"])
def test_sc_13_level_change_and_removal_on_two_connections(
    start_process, tmp_path, first
):
    """change_level and remove serialize on the settings lock across processes."""
    a, b = start_process(), start_process()
    a.ask("migrate")
    a.ask("level_setup")
    held, release = tmp_path / "held", tmp_path / "release"
    if first == "remove":
        # A removes alpha and pauses at the gateway step, holding the lock;
        # B tries to choose alpha for Complex at the same time.
        send(
            a,
            action="level_race",
            step="remove",
            model="alpha",
            held=str(held),
            release=str(release),
        )
        wait_until(held)
        send(
            b, action="level_race", step="change_level", level="complex", model="alpha"
        )
    else:
        # A chooses alpha for Complex and pauses after its record, holding
        # the lock; B tries to remove alpha at the same time.
        send(
            a,
            action="level_race",
            step="change_level",
            level="complex",
            model="alpha",
            held=str(held),
            release=str(release),
        )
        wait_until(held)
        send(b, action="level_race", step="remove", model="alpha")
    # B waits for A's lock instead of deciding on what it read earlier.
    assert answer(b, 1.5) is None
    release.write_text("go")
    first_result = answer(a, 30)
    second_result = answer(b, 30)
    assert first_result is not None and second_result is not None
    if first == "remove":
        assert first_result["removed"] is True
        assert second_result["level_error"] == "Choose a model that is set up"
        assert second_result["choices"] == {}
        assert second_result["models"] == ["beta"]
        assert second_result["records"] == ["Removed model alpha from the gateway"]
    else:
        assert first_result["changed"] is True
        assert second_result["in_use"] == ["Complex"]
        assert second_result["choices"] == {"complex": "alpha"}
        assert second_result["models"] == ["alpha", "beta"]
        assert second_result["records"] == [LEVEL_RECORDS[0]]
