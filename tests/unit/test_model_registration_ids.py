"""Outgoing native resource IDs stay explicit without rewriting old definitions."""

import copy
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from model_registry import registration
from model_registry.fingerprints import fingerprint
from model_registry.registration import ModelManagement


class Gateway:
    def __init__(self):
        self.records, self.writes = {}, []

    def resources(self):
        return 200, {"resources": copy.deepcopy(list(self.records.values()))}

    def request(self, path, body=None, method=None, **_):
        if body is None and method != "DELETE":
            if path == "/v1/models":
                return 200, {"data": [{"id": name} for name in self.records]}
            return self.resources()
        if path == "/v1/chat/completions":
            assert body["model"] in self.records
            return 200, {"choices": [{"message": {"content": "OK"}}]}
        if method == "DELETE":
            del self.records[path.rsplit("/", 1)[1]]
        else:
            for value in (
                [row["value"] for row in body["resources"]]
                if "resources" in body
                else [body["value"]]
            ):
                model_id = value["name"]
                self.writes.append(copy.deepcopy(value))
                self.records[model_id] = {
                    "id": model_id,
                    "revision": self.records.get(model_id, {}).get("revision", 0) + 1,
                    "value": copy.deepcopy(value),
                }
        return 200, {}


class Catalog:
    def __init__(self):
        self.rows = {}

    def get(self, model_id):
        return self.rows.get(model_id)

    def approve(self, model_id, classes, revision, actor, **options):
        self.rows[model_id] = {
            "approved_classes": classes,
            "gateway_fingerprint": revision,
            "key_choice": "none",
            **options,
        }
        return self.rows[model_id]


@pytest.mark.parametrize("source", [[], {}])
def test_malformed_source_is_rejected_before_gateway_or_storage_contact(source):
    def unexpected(*args, **kwargs):
        raise AssertionError("Invalid model input must not contact storage or gateway")

    forbidden = SimpleNamespace(enabled=unexpected, list=unexpected, request=unexpected, resources=unexpected)
    registrar = ModelManagement(object(), forbidden, forbidden, None, "managed", None, "", set(), {"openai": "", "anthropic": ""}, "")
    status, body = registrar.add({"name": "model", "model": "upstream", "source": source})
    assert status == 400 and body == {"error": "Choose a supported model source"}


@pytest.fixture
def registrar(tmp_path, monkeypatch):
    def save(directory, value):
        # This contract check does not exercise native UID65532 file ownership.
        path = Path(directory) / ("key-" + uuid.uuid4().hex)
        path.parent.mkdir(exist_ok=True)
        path.write_text(value)
        path.chmod(0o600)
        return str(path)

    monkeypatch.setattr(registration, "save_provider_key", save)
    gateway, catalog = Gateway(), Catalog()
    result = ModelManagement(
        catalog,
        SimpleNamespace(enabled=lambda: False, list=list),
        gateway,
        None,
        "managed",
        None,
        str(tmp_path / "keys"),
        set(),
        {
            "openai": "http://provider.invalid/v1",
            "anthropic": "http://provider.invalid",
        },
        "",
    )
    result.local_runner = lambda *_: (200, {})
    return result


@pytest.mark.parametrize(
    "source,choice",
    [
        ("fixture", "none"),
        ("runner", "none"),
        ("openai", "none"),
        ("anthropic", "none"),
        ("openai", "shared"),
        ("anthropic", "shared"),
    ],
)
def test_new_registration_has_explicit_api_id_and_complete_approval(
    registrar, source, choice
):
    body = {
        "name": "stable-model",
        "model": "upstream",
        "source": source,
        "key_choice": choice,
        "shared_key": "synthetic-shared-provider-key",
        "address": "http://runner.invalid",
    }
    assert registrar.add(body)[0] == 200
    entry = registrar.gateway.records[body["name"]]
    assert entry["value"]["id"] == entry["id"] == body["name"]
    assert registrar.catalog.get(entry["id"])["gateway_fingerprint"] == fingerprint(
        entry["id"], [entry]
    )
    changed = copy.deepcopy(entry)
    changed["value"]["id"] = "different-native-target"
    assert fingerprint(entry["id"], [changed]) != fingerprint(entry["id"], [entry])


@pytest.mark.parametrize("explicit", [False, True])
def test_shared_key_check_has_unique_id_and_preserves_original_definition_identity(
    registrar, explicit
):
    assert (
        registrar.add(
            {
                "name": "stable-model",
                "model": "upstream",
                "source": "openai",
                "key_choice": "shared",
                "shared_key": "synthetic-original-provider-key",
            }
        )[0]
        == 200
    )
    entry = registrar.gateway.records["stable-model"]
    if not explicit:
        del entry["value"]["id"]
    previous = registrar.catalog.get("stable-model")
    previous["gateway_fingerprint"] = fingerprint("stable-model", [entry])
    resource = copy.deepcopy(entry["value"])
    registrar.gateway.writes.clear()
    assert (
        registrar.replace_shared_key(
            "stable-model", resource, previous, [], "synthetic-replacement-provider-key"
        )[0]
        == 200
    )
    temporary, updated = registrar.gateway.writes
    assert temporary["id"] == temporary["name"]
    assert (
        temporary["id"].startswith("keeplane-keycheck-")
        and temporary["id"] != "stable-model"
    )
    assert ("id" in updated) == explicit
    if explicit:
        assert updated["id"] == "stable-model"
    assert set(registrar.gateway.records) == {"stable-model"}
    assert registrar.catalog.get("stable-model")["gateway_fingerprint"] == fingerprint(
        "stable-model", registrar.gateway.resources()[1]["resources"]
    )


def test_existing_name_only_registration_and_setup_never_add_id(registrar):
    value = {
        "name": "legacy",
        "provider": {"custom": {"formats": [{"type": "completions"}]}},
        "params": {"model": "upstream", "baseUrl": "http://model:18080/v1"},
    }
    registrar.gateway.records["legacy"] = {
        "id": "legacy",
        "revision": 1,
        "value": value,
    }
    original = copy.deepcopy(registrar.gateway.records)
    revision = fingerprint("legacy", list(original.values()))
    registrar.catalog.approve("legacy", [], revision, None, owned_by_keeplane=True)
    assert registrar.add(
        {"name": "legacy", "model": "upstream", "source": "fixture"}
    ) == (200, {"name": "legacy", "existing": True})
    assert registrar.setup("legacy", {"key_choice": "none"})[0] == 200
    assert registrar.gateway.records == original and not registrar.gateway.writes
    assert registrar.catalog.get("legacy")["gateway_fingerprint"] == revision
