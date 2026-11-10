"""Spec 004 ST10, ST23, ST24 and ST26: adding and setting up models (fakes only).

The plain-English cases are MRS-01 to MRS-14 in models-routing-cases.md. The
gateway is an in-memory store and the local runner a loopback HTTP server, so
no Docker, gateway or provider is used.
"""

import copy
import json
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from types import SimpleNamespace

import pytest
from common.errors import StorageUnavailable
from integrations.runners import local_runner
from model_registry import registration
from model_registry.fingerprints import fingerprint
from model_registry.registration import ModelManagement

ACTOR = ("admin-id", "first-admin")
CLASSES = [{"name": "Public"}, {"name": "Internal"}]


class Gateway:
    """One gateway's model store, its model list and its chat answers."""

    def __init__(self):
        self.records = {}
        self.writes, self.deletes, self.asked = [], [], []
        self.answer = (200, {"choices": [{"message": {"content": "OK"}}]})
        self.write_status = 200
        self.delete_status = 200

    def put(self, value, revision=1):
        self.records[value["name"]] = {
            "id": value["name"],
            "revision": revision,
            "value": copy.deepcopy(value),
        }

    def resources(self):
        return 200, {"resources": copy.deepcopy(list(self.records.values()))}

    def request(self, path, body=None, method=None, **_):
        if method == "DELETE":
            model_id = path.rsplit("/", 1)[1]
            self.deletes.append(model_id)
            if self.delete_status != 200:
                return self.delete_status, {"error": "delete refused"}
            self.records.pop(model_id, None)
            return 200, {}
        if body is None:
            if path == "/v1/models":
                return 200, {"data": [{"id": name} for name in self.records]}
            return self.resources()
        if path == "/v1/chat/completions":
            self.asked.append(body["model"])
            return self.answer
        if self.write_status != 200:
            return self.write_status, {"error": "write refused"}
        for row in body["resources"]:
            value = row["value"]
            self.writes.append(copy.deepcopy(value))
            previous = self.records.get(value["name"], {}).get("revision", 0)
            self.put(value, previous + 1)
        return 200, {}


class Catalog:
    def __init__(self, rows=None):
        self.rows = rows or {}

    def get(self, model_id):
        row = self.rows.get(model_id)
        return copy.deepcopy(row) if row else None

    def approve(self, model_id, classes, revision, actor, **options):
        self.rows[model_id] = {
            "approved_classes": list(classes),
            "gateway_fingerprint": revision,
            "key_choice": options.get("key_choice", "none"),
            "owned_by_keeplane": options.get("owned_by_keeplane", False),
        }
        return self.get(model_id)


def management(gateway, catalog, tmp_path, monkeypatch, *, classes_on, mode="managed", runners=()):
    def save(directory, value):
        path = Path(directory) / ("key-" + uuid.uuid4().hex)
        path.parent.mkdir(exist_ok=True)
        path.write_text(value)
        return str(path)

    def remove(directory, path):
        Path(path).unlink(missing_ok=True)
        return True

    monkeypatch.setattr(registration, "save_provider_key", save)
    monkeypatch.setattr(registration, "remove_provider_key", remove)
    monkeypatch.setattr(
        registration,
        "managed_provider_key",
        lambda directory, path: bool(path) and Path(path).parent == Path(directory),
    )
    monkeypatch.setattr(registration.time, "sleep", lambda _: None)
    return ModelManagement(
        catalog,
        SimpleNamespace(enabled=lambda: classes_on, list=lambda: CLASSES),
        gateway,
        ACTOR,
        mode,
        None,
        str(tmp_path / "keys"),
        set(runners),
        {"openai": "http://provider.invalid/v1", "anthropic": "http://provider.invalid"},
        "",
    )


def cloud(source="openai", key_choice="shared", **extra):
    body = {"name": "coder", "model": "coder", "source": source, "key_choice": key_choice}
    if key_choice == "shared":
        body["shared_key"] = "synthetic-shared-provider-key"
    return body | extra


def key_files(tmp_path):
    folder = tmp_path / "keys"
    return sorted(folder.iterdir()) if folder.exists() else []


class Runner(BaseHTTPRequestHandler):
    """A local runner that serves one model and records every request."""

    def do_GET(self):
        self.server.seen.append(("GET", self.path))
        if self.path == "/v1/models":
            return self.reply({"data": [{"id": "runner-model"}]})
        if self.path == "/props":
            return self.reply({"default_generation_settings": {"n_ctx": 8192}})
        self.send_error(404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        self.server.seen.append(("POST", self.path, json.loads(self.rfile.read(length))))
        if self.path != "/v1/chat/completions" or self.server.down:
            return self.send_error(503)
        self.reply({"choices": [{"message": {"content": "OK"}}]})

    def reply(self, body):
        data = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *_):
        pass


@pytest.fixture
def runner(monkeypatch):
    monkeypatch.setenv("no_proxy", "*")
    monkeypatch.setenv("NO_PROXY", "*")
    server = ThreadingHTTPServer(("127.0.0.1", 0), Runner)
    server.seen, server.down = [], False
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    server.address = f"http://127.0.0.1:{server.server_port}"
    yield server
    server.shutdown()
    server.server_close()


def test_mrs_01_a_cloud_model_is_checked_saved_with_its_key_and_classes_and_registered(
    tmp_path, monkeypatch
):
    gateway, catalog = Gateway(), Catalog()
    status, body = management(gateway, catalog, tmp_path, monkeypatch, classes_on=True).add(
        cloud(approved_classes=["Public", "Internal"])
    )
    assert status == 200
    assert body == {"name": "coder", "key_choice": "shared", "approved_classes": ["Public", "Internal"]}
    # Keeplane asked the model through the gateway before saving.
    assert gateway.asked == ["coder"]
    entry = gateway.records["coder"]["value"]
    assert entry["provider"] == "openAI" and entry["params"]["model"] == "coder"
    (key,) = key_files(tmp_path)
    assert entry["auth"] == {"key": {"value": {"file": str(key)}}}
    assert catalog.get("coder") == {
        "approved_classes": ["Public", "Internal"],
        "gateway_fingerprint": fingerprint("coder", gateway.resources()[1]["resources"]),
        "key_choice": "shared",
        "owned_by_keeplane": True,
    }


def test_mrs_02_with_data_classes_off_a_model_is_added_with_no_class(tmp_path, monkeypatch):
    gateway, catalog = Gateway(), Catalog()
    status, body = management(gateway, catalog, tmp_path, monkeypatch, classes_on=False).add(
        cloud(key_choice="none", approved_classes=["Public"])
    )
    assert status == 200 and body["approved_classes"] == []
    assert catalog.get("coder")["approved_classes"] == []


def test_mrs_03_on_the_customers_gateway_the_model_is_registered_there(tmp_path, monkeypatch):
    customer, catalog = Gateway(), Catalog()
    status, _ = management(
        customer, catalog, tmp_path, monkeypatch, classes_on=False, mode="existing"
    ).add(cloud(key_choice="none"))
    assert status == 200
    assert [value["name"] for value in customer.writes] == ["coder"]
    assert catalog.get("coder")["owned_by_keeplane"] is True


def test_mrs_04_find_models_lists_the_runner_and_its_model_is_added_with_no_key(
    tmp_path, monkeypatch, runner
):
    assert local_runner(runner.address, {runner.address}) == (
        200,
        {"models": ["runner-model"], "runtime": {"runner-model": {"active_context_tokens": 8192}}},
    )
    gateway, catalog = Gateway(), Catalog()
    status, _ = management(
        gateway, catalog, tmp_path, monkeypatch, classes_on=True, runners={runner.address}
    ).add(
        {
            "name": "runner-model",
            "model": "runner-model",
            "source": "runner",
            "address": runner.address,
            "approved_classes": ["Internal"],
        }
    )
    assert status == 200
    entry = gateway.records["runner-model"]["value"]
    assert entry["params"] == {"model": "runner-model", "baseUrl": runner.address + "/v1"}
    assert "auth" not in entry
    saved = catalog.get("runner-model")
    assert saved["key_choice"] == "none" and saved["approved_classes"] == ["Internal"]
    assert key_files(tmp_path) == []


@pytest.mark.parametrize(
    "case,source,answer,reason",
    [
        ("runner", "runner", None, "The runner at {address} didn't answer."),
        ("provider down", "openai", (503, {}), "OpenAI didn't answer."),
        ("provider down", "anthropic", (502, {}), "Anthropic didn't answer."),
        ("key refused", "openai", (401, {}), "OpenAI refused the key."),
        ("key refused", "anthropic", (403, {}), "Anthropic refused the key."),
    ],
)
def test_mrs_05_a_model_that_does_not_answer_is_not_added_and_nothing_is_saved(
    tmp_path, monkeypatch, runner, case, source, answer, reason
):
    gateway, catalog = Gateway(), Catalog()
    manager = management(
        gateway, catalog, tmp_path, monkeypatch, classes_on=True, runners={runner.address}
    )
    if source == "runner":
        runner.down = True
        body = {"name": "runner-model", "model": "runner-model", "source": "runner", "address": runner.address}
    else:
        gateway.answer = answer
        body = cloud(source)
    status, result = manager.add(body)
    assert status == 503
    assert result == {"error": reason.format(address=runner.address) + " Nothing was saved."}
    assert gateway.records == {} and catalog.rows == {} and key_files(tmp_path) == []
    if source == "runner":
        assert gateway.writes == []


@pytest.mark.parametrize("body", [cloud(), {"name": "local", "model": "upstream", "source": "fixture"}])
def test_mrs_06_a_model_the_gateway_does_not_register_is_not_added(tmp_path, monkeypatch, body):
    gateway, catalog = Gateway(), Catalog()
    gateway.write_status = 500
    status, result = management(gateway, catalog, tmp_path, monkeypatch, classes_on=True).add(body)
    assert status == 503
    assert result == {"error": "The gateway didn't register it. Nothing was saved."}
    assert gateway.records == {} and catalog.rows == {} and key_files(tmp_path) == []


@pytest.mark.parametrize("source,label", [("openai", "OpenAI"), ("anthropic", "Anthropic")])
def test_mrs_07_the_same_model_from_the_same_provider_is_already_added(
    tmp_path, monkeypatch, source, label
):
    gateway, catalog = Gateway(), Catalog()
    manager = management(gateway, catalog, tmp_path, monkeypatch, classes_on=False)
    assert manager.add(cloud(source))[0] == 200
    before = (copy.deepcopy(gateway.records), catalog.get("coder"), key_files(tmp_path))
    status, result = manager.add(cloud(source, name="coder-again"))
    assert (status, result) == (409, {"error": f"coder from {label} is already added."})
    assert (gateway.records, catalog.get("coder"), key_files(tmp_path)) == before
    assert catalog.get("coder-again") is None


def test_mrs_08_editing_with_replace_shared_key_empty_keeps_the_current_key(
    tmp_path, monkeypatch
):
    gateway, catalog = Gateway(), Catalog()
    manager = management(gateway, catalog, tmp_path, monkeypatch, classes_on=True)
    assert manager.add(cloud(approved_classes=["Public"]))[0] == 200
    (key,) = key_files(tmp_path)
    definition = copy.deepcopy(gateway.records["coder"])
    writes = len(gateway.writes)
    status, result = manager.setup(
        "coder", {"key_choice": "shared", "approved_classes": ["Public"], "replace_shared_key": ""}
    )
    assert status == 200 and result["key_choice"] == "shared"
    # Keeplane asked the model again, wrote nothing to the gateway and kept the key file.
    assert gateway.asked == ["coder", "coder"]
    assert len(gateway.writes) == writes and gateway.records["coder"] == definition
    assert key_files(tmp_path) == [key] and key.read_text() == "synthetic-shared-provider-key"


def test_mrs_09_a_model_added_outside_keeplane_is_set_up_with_data_classes_off(
    tmp_path, monkeypatch
):
    gateway, catalog = Gateway(), Catalog()
    gateway.put(
        {
            "id": "outside",
            "name": "outside",
            "provider": {"custom": {"formats": [{"type": "completions"}]}},
            "params": {"model": "outside", "baseUrl": "http://model:18080/v1"},
        }
    )
    status, result = management(gateway, catalog, tmp_path, monkeypatch, classes_on=False).setup(
        "outside", {"key_choice": "none"}
    )
    assert status == 200
    assert result == {
        "approved_classes": [],
        "gateway_fingerprint": fingerprint("outside", gateway.resources()[1]["resources"]),
        "key_choice": "none",
        "owned_by_keeplane": False,
    }
    assert gateway.writes == [] and gateway.asked == ["outside"]


def test_mrs_10_keeplane_only_reads_and_asks_a_local_runner(tmp_path, monkeypatch, runner):
    local_runner(runner.address, {runner.address})
    management(
        Gateway(), Catalog(), tmp_path, monkeypatch, classes_on=False, runners={runner.address}
    ).add({"name": "runner-model", "model": "runner-model", "source": "runner", "address": runner.address})
    reads = {row for row in runner.seen if row[0] == "GET"}
    asks = [row for row in runner.seen if row[0] == "POST"]
    assert reads == {("GET", "/v1/models"), ("GET", "/props")}
    # One short question; no settings, load, unload or restart request.
    assert asks == [
        (
            "POST",
            "/v1/chat/completions",
            {"model": "runner-model", "messages": [{"role": "user", "content": "Reply OK."}], "max_tokens": 1},
        )
    ]


LOCAL = {"name": "local", "model": "upstream", "source": "fixture", "approved_classes": ["Public"]}


def test_mrs_11_a_local_model_that_does_not_answer_through_the_gateway_is_not_added(
    tmp_path, monkeypatch
):
    gateway, catalog = Gateway(), Catalog()
    gateway.answer = (503, {})
    status, result = management(gateway, catalog, tmp_path, monkeypatch, classes_on=True).add(LOCAL)
    assert status == 503
    assert result == {"error": "The model didn't answer through the gateway. Nothing was saved."}
    assert gateway.asked == ["local"] and gateway.deletes == ["local"]
    assert gateway.records == {} and catalog.rows == {}


def test_mrs_11_when_its_entry_cannot_be_removed_keeplane_does_not_say_nothing_was_saved(
    tmp_path, monkeypatch
):
    gateway, catalog = Gateway(), Catalog()
    gateway.answer, gateway.delete_status = (503, {}), 500
    status, result = management(gateway, catalog, tmp_path, monkeypatch, classes_on=True).add(LOCAL)
    assert status == 503
    assert result == {
        "error": "The model didn't answer through the gateway. "
        "The model may remain in the gateway without Keeplane approval. Check Models."
    }
    assert "Nothing was saved" not in result["error"]
    assert "local" in gateway.records and catalog.rows == {}


class RefusingCatalog(Catalog):
    def approve(self, *_, **__):
        raise StorageUnavailable("approval storage is down")


@pytest.mark.parametrize("body", [LOCAL, cloud(approved_classes=["Public"])])
def test_mrs_12_when_the_approval_cannot_be_saved_the_model_is_removed_and_nothing_is_saved(
    tmp_path, monkeypatch, body
):
    gateway, catalog = Gateway(), RefusingCatalog()
    status, result = management(gateway, catalog, tmp_path, monkeypatch, classes_on=True).add(body)
    assert status == 503
    assert result == {
        "error": "Keeplane couldn't save the model approval. Nothing was saved."
    }
    assert gateway.records == {} and catalog.rows == {} and key_files(tmp_path) == []


@pytest.mark.parametrize("body", [LOCAL, cloud(approved_classes=["Public"])])
def test_mrs_12_when_the_model_cannot_be_removed_either_keeplane_does_not_say_nothing_was_saved(
    tmp_path, monkeypatch, body
):
    gateway, catalog = Gateway(), RefusingCatalog()
    gateway.delete_status = 500
    status, result = management(gateway, catalog, tmp_path, monkeypatch, classes_on=True).add(body)
    assert status == 503
    assert result == {
        "error": "Keeplane couldn't save the model approval. The model may remain "
        "in the gateway without Keeplane approval. Check Models."
    }
    assert "Nothing was saved" not in result["error"]


MAY_REMAIN = "The model may remain in the gateway without Keeplane approval. Check Models."


class FlakyWrites(Gateway):
    """A gateway whose numbered model writes fail, applied or not."""

    def __init__(self, applied_but_failed=(), failing_from=None):
        super().__init__()
        self.applied_but_failed = set(applied_but_failed)
        self.failing_from = failing_from
        self.model_writes = 0

    def request(self, path, body=None, method=None, **options):
        if body is None or method == "DELETE" or path == "/v1/chat/completions":
            return super().request(path, body, method, **options)
        self.model_writes += 1
        if self.failing_from and self.model_writes >= self.failing_from:
            return 500, {"error": "write refused"}
        if "value" in body:
            # One model written in place, as a key replacement does.
            body = {"resources": [{"value": body["value"]}]}
        status, result = super().request(path, body, method, **options)
        if self.model_writes in self.applied_but_failed:
            return 500, {"error": "write timed out"}
        return status, result


@pytest.mark.parametrize("body", [cloud(approved_classes=["Public"]), LOCAL])
def test_mrs_13_when_an_unregistered_model_cannot_be_removed_keeplane_says_to_check_models(
    tmp_path, monkeypatch, body
):
    gateway, catalog = FlakyWrites(applied_but_failed={1}), Catalog()
    gateway.delete_status = 500
    status, result = management(gateway, catalog, tmp_path, monkeypatch, classes_on=True).add(body)
    assert status == 503
    assert result == {"error": "The gateway didn't register it. " + MAY_REMAIN}
    assert "Nothing was saved" not in result["error"]
    assert body["name"] in gateway.records and catalog.rows == {}


@pytest.mark.parametrize(
    "source,answer,reason",
    [
        ("openai", (401, {}), "OpenAI refused the key."),
        ("anthropic", (503, {}), "Anthropic didn't answer."),
    ],
)
def test_mrs_13_when_a_cloud_model_that_does_not_answer_cannot_be_removed_keeplane_says_to_check_models(
    tmp_path, monkeypatch, source, answer, reason
):
    gateway, catalog = Gateway(), Catalog()
    gateway.answer, gateway.delete_status = answer, 500
    status, result = management(gateway, catalog, tmp_path, monkeypatch, classes_on=True).add(
        cloud(source, approved_classes=["Public"])
    )
    assert status == 503
    assert result == {"error": f"{reason} {MAY_REMAIN}"}
    assert "Nothing was saved" not in result["error"]
    assert "coder" in gateway.records and catalog.rows == {}


class RefusingReplacement(Catalog):
    def approve(self, model_id, classes, revision, actor, **options):
        if options.get("shared_key_replaced"):
            raise StorageUnavailable("approval storage is down")
        return super().approve(model_id, classes, revision, actor, **options)


def replace_key(gateway, catalog, tmp_path, monkeypatch):
    manager = management(gateway, catalog, tmp_path, monkeypatch, classes_on=True)
    assert manager.add(cloud(approved_classes=["Public"]))[0] == 200
    return manager.setup(
        "coder",
        {
            "key_choice": "shared",
            "approved_classes": ["Public"],
            "replace_shared_key": "synthetic-replacement-provider-key",
        },
    )


def test_mrs_14_when_the_key_check_model_cannot_be_removed_keeplane_says_to_check_models(
    tmp_path, monkeypatch
):
    class RefusesTheCheck(Gateway):
        def request(self, path, body=None, method=None, **options):
            if path == "/v1/chat/completions" and body["model"].startswith("keeplane-keycheck-"):
                self.asked.append(body["model"])
                return 401, {}
            return super().request(path, body, method, **options)

    gateway = RefusesTheCheck()
    gateway.delete_status = 500
    status, result = replace_key(gateway, Catalog(), tmp_path, monkeypatch)
    assert (status, result) == (
        503,
        {
            "error": "The replacement key didn't answer through the gateway. "
            "A verification model may need cleanup. Check Models."
        },
    )


@pytest.mark.parametrize(
    "case,gateway,catalog,error",
    [
        (
            "the model doesn't confirm the new key",
            # 1 adds, 2 is the key check, 3 the replacement (applied, refused), 4 the restore.
            lambda: FlakyWrites(applied_but_failed={3}, failing_from=4),
            Catalog,
            "The replacement key didn't work. The model may need admin attention. Check Models.",
        ),
        (
            "Keeplane can't save the change",
            lambda: FlakyWrites(failing_from=4),
            RefusingReplacement,
            "Keeplane couldn't save the change. The model may need admin attention. Check Models.",
        ),
    ],
)
def test_mrs_14_when_the_previous_key_cannot_be_restored_keeplane_says_to_check_models(
    tmp_path, monkeypatch, case, gateway, catalog, error
):
    status, result = replace_key(gateway(), catalog(), tmp_path, monkeypatch)
    assert (status, result) == (503, {"error": error})
    assert "previous key is still active" not in error


SHARED_REFUSED = (
    "Keeplane can't pass a shared key to a gateway it doesn't run yet, so use No key "
    "for this model. Nothing was saved."
)
OWN_REFUSED = (
    "Keeplane can't pass developers' own keys to a gateway it doesn't run yet, so use "
    "No key for this model. Nothing was saved."
)


def watched(gateway):
    """Record every gateway call, reads included."""
    calls, original = [], gateway.request

    def request(path, body=None, method=None, **options):
        calls.append((method or ("POST" if body is not None else "GET"), path))
        return original(path, body, method, **options)

    gateway.request = request
    return calls


@pytest.mark.parametrize("source", ["openai", "anthropic"])
@pytest.mark.parametrize(
    "key_choice,error", [("shared", SHARED_REFUSED), ("personal", OWN_REFUSED)]
)
def test_mrs_15_the_customers_gateway_refuses_shared_and_own_keys_on_add(
    tmp_path, monkeypatch, source, key_choice, error
):
    customer, catalog = Gateway(), Catalog()
    calls = watched(customer)
    status, body = management(
        customer, catalog, tmp_path, monkeypatch, classes_on=True, mode="existing"
    ).add(cloud(source=source, key_choice=key_choice, approved_classes=["Public"]))
    assert (status, body) == (422, {"error": error})
    assert calls == [] and customer.records == {}
    assert catalog.rows == {} and key_files(tmp_path) == []


def test_mrs_16_the_customers_gateway_refuses_own_keys_on_edit_and_set_up(
    tmp_path, monkeypatch
):
    customer = Gateway()
    customer.put(
        {"id": "coder", "name": "coder", "provider": "openAI", "params": {"model": "coder"}}
    )
    revision = fingerprint("coder", customer.resources()[1]["resources"])
    saved = {
        "approved_classes": ["Public"],
        "gateway_fingerprint": revision,
        "key_choice": "personal",
        "owned_by_keeplane": True,
    }
    # Edit: a model set up for developers' own keys before this rule.
    # Set up: a model only in the customer's gateway.
    for rows, model_id in (({"coder": dict(saved)}, "coder"), ({}, "coder")):
        catalog = Catalog(copy.deepcopy(rows))
        calls = watched(customer)
        status, body = management(
            customer, catalog, tmp_path, monkeypatch, classes_on=True, mode="existing"
        ).setup(model_id, {"key_choice": "personal", "approved_classes": ["Internal"]})
        assert (status, body) == (422, {"error": OWN_REFUSED})
        assert calls == [] and catalog.rows == rows
        assert customer.writes == [] and customer.records["coder"]["revision"] == 1
    # A No key setup on the same gateway still works.
    status, _ = management(
        customer, Catalog(), tmp_path, monkeypatch, classes_on=True, mode="existing"
    ).setup("coder", {"key_choice": "none", "approved_classes": ["Public"]})
    assert status == 200


def test_mrs_18_an_earlier_own_key_model_can_only_move_to_no_key(tmp_path, monkeypatch):
    customer = Gateway()
    customer.put(
        {"id": "coder", "name": "coder", "provider": "openAI", "params": {"model": "coder"}}
    )
    revision = fingerprint("coder", customer.resources()[1]["resources"])
    saved = {
        "approved_classes": ["Public"],
        "gateway_fingerprint": revision,
        "key_choice": "personal",
        "owned_by_keeplane": True,
    }
    catalog = Catalog({"coder": dict(saved)})
    manager = management(
        customer, catalog, tmp_path, monkeypatch, classes_on=True, mode="existing"
    )
    calls = watched(customer)
    # Any other edit: a shared key, or No key with different classes.
    for body in (
        {"key_choice": "shared", "approved_classes": ["Public"]},
        {"key_choice": "none", "approved_classes": ["Internal"]},
        {"key_choice": "none", "approved_classes": []},
        {"key_choice": "none", "approved_classes": ["Public"], "replace_shared_key": "x" * 20},
    ):
        assert manager.setup("coder", body) == (422, {"error": OWN_REFUSED})
    assert calls == [] and catalog.rows == {"coder": saved}
    # Moving it to No key with its classes is saved, after the model answers.
    status, result = manager.setup("coder", {"key_choice": "none", "approved_classes": ["Public"]})
    assert status == 200
    assert result == saved | {"key_choice": "none"}
    assert customer.writes == [] and customer.asked == ["coder"]


def test_mrs_17_a_managed_gateway_still_takes_developers_own_keys(tmp_path, monkeypatch):
    gateway, catalog = Gateway(), Catalog()
    manager = management(gateway, catalog, tmp_path, monkeypatch, classes_on=False)
    monkeypatch.setattr(manager, "provider_probe", lambda *a, **k: True)
    status, body = manager.add(cloud(key_choice="personal"))
    assert status == 200 and body["key_choice"] == "personal"
