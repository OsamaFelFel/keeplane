"""Model changes are confirmed on every gateway serving copy (fakes, no Docker)."""

import copy
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from integrations.gateway import copies as copies_module
from integrations.gateway.copies import (
    CopyReadback,
    GatewayCopies,
    GatewayCopiesUnavailable,
    copy_urls,
)
from model_registry import registration
from model_registry.fingerprints import fingerprint
from model_registry.registration import NOT_EVERY_COPY, ModelManagement
from model_registry.removal import NOT_GONE_EVERYWHERE, remove_model_setup

ACTOR = ("admin-id", "first-admin")
OTHER = {
    "id": "other-model",
    "revision": 4,
    "value": {
        "id": "other-model",
        "name": "other-model",
        "provider": {"custom": {"formats": [{"type": "completions"}]}},
        "params": {"model": "other", "baseUrl": "http://model:18080/v1"},
    },
}


class Store:
    """The gateway address: one model store shared by every serving copy."""

    def __init__(self):
        self.records = {OTHER["id"]: copy.deepcopy(OTHER)}
        self.writes = []

    def snapshot(self):
        return copy.deepcopy(list(self.records.values()))

    def resources(self):
        return 200, {"resources": self.snapshot()}

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
            return 200, {}
        for value in (
            [row["value"] for row in body["resources"]]
            if "resources" in body
            else [body["value"]]
        ):
            self.writes.append(copy.deepcopy(value))
            model_id = value["name"]
            self.records[model_id] = {
                "id": model_id,
                "revision": self.records.get(model_id, {}).get("revision", 0) + 1,
                "value": copy.deepcopy(value),
            }
        return 200, {}

    def delete_model(self, model_id):
        return self.request(
            "/api/config/resources/llm.model/" + model_id, method="DELETE"
        )


class Copy:
    """A serving copy reading the shared store.

    lag: reads before it shows the store's current state (it shows the state
    from when it was frozen until then). stale: never catches up. down: the
    management read fails.
    """

    def __init__(self, store, lag=0, stale=False, down=False):
        self.store, self.lag, self.stale, self.down = store, lag, stale, down
        self.frozen = store.snapshot()
        self.reads = 0

    def freeze(self):
        self.frozen = self.store.snapshot()

    def request(self, path, body=None, method=None, **_):
        assert body is None and method is None, "copies are only read"
        assert path == "/api/config/resources/llm.model"
        self.reads += 1
        if self.down:
            return 503, {"error": "Gateway unavailable"}
        if self.stale or self.reads <= self.lag:
            return 200, {"resources": copy.deepcopy(self.frozen)}
        return 200, {"resources": self.store.snapshot()}


class Catalog:
    def __init__(self):
        self.rows = {
            OTHER["id"]: {
                "approved_classes": ["Public"],
                "gateway_fingerprint": fingerprint(OTHER["id"], [OTHER]),
                "key_choice": "none",
                "owned_by_keeplane": True,
            }
        }
        self.removed = []

    def get(self, model_id):
        row = self.rows.get(model_id)
        return copy.deepcopy(row) if row else None

    def approve(self, model_id, classes, revision, actor, **options):
        self.rows[model_id] = {
            "approved_classes": classes,
            "gateway_fingerprint": revision,
            "key_choice": options.get("key_choice", "none"),
            "owned_by_keeplane": options.get("owned_by_keeplane", False),
        }
        return self.get(model_id)

    def routing_uses(self, model_id):
        return {"levels": [], "persona_rules": []}

    def remove(self, model_id, actor, remove_from_gateway=None):
        if remove_from_gateway:
            status, _ = remove_from_gateway()
            assert status == 200
        self.removed.append(model_id)
        return self.rows.pop(model_id, None) is not None


def no_sleep(_):
    return None


def copies_of(*serving):
    return GatewayCopies(serving, attempts=3, pause=0.5, sleep=no_sleep)


def manager(store, catalog, serving, tmp_path, monkeypatch, classes_on=False):
    def save(directory, value):
        path = Path(directory) / ("key-" + uuid.uuid4().hex)
        path.parent.mkdir(exist_ok=True)
        path.write_text(value)
        return str(path)

    monkeypatch.setattr(registration, "save_provider_key", save)
    monkeypatch.setattr(
        registration,
        "managed_provider_key",
        lambda directory, path: bool(path) and Path(path).parent == Path(directory),
    )
    result = ModelManagement(
        catalog,
        SimpleNamespace(
            enabled=lambda: classes_on,
            list=lambda: [{"name": "Public"}, {"name": "Internal"}],
        ),
        store,
        ACTOR,
        "managed",
        None,
        str(tmp_path / "keys"),
        set(),
        {
            "openai": "http://provider.invalid/v1",
            "anthropic": "http://provider.invalid",
        },
        "",
        copies=serving,
    )
    result.local_runner = lambda *_: (200, {})
    return result


# GC-01 / GC-02: the operator's list of copies.


def test_gc_01_copy_list_is_parsed_and_any_bad_entry_refuses_the_list():
    assert copy_urls("") == []
    assert copy_urls(" http://gw-0:4000/ , https://gw-1:4000,http://gw-0:4000") == [
        "http://gw-0:4000",
        "https://gw-1:4000",
    ]
    for bad in (
        "ftp://gw-0:4000",
        "http://user:secret@gw-0:4000",
        "http://gw-0:4000/api",
        "http://gw-0:4000?x=1",
        "http://gw-0:4000,gw-1",
        "http://gw-0:40\x0700",
    ):
        with pytest.raises(GatewayCopiesUnavailable):
            copy_urls(bad)
    with pytest.raises(GatewayCopiesUnavailable):
        copy_urls(",".join(f"http://gw-{n}:4000" for n in range(33)))


def test_gc_02_environment_builds_copies_with_the_gateway_credentials_or_fails_closed():
    primary = SimpleNamespace(runtime_key_file="/run/r", admin_key_file="/run/a")
    built = GatewayCopies.from_environment(
        primary, {"GATEWAY_COPY_URLS": "http://gw-0:4000,http://gw-1:4000"}
    )
    assert [c.base_url for c in built.copies] == [
        "http://gw-0:4000",
        "http://gw-1:4000",
    ]
    assert {(c.runtime_key_file, c.admin_key_file) for c in built.copies} == {
        ("/run/r", "/run/a")
    }
    assert GatewayCopies.from_environment(primary, {}).confirm("m", None).complete
    refused = GatewayCopies.from_environment(
        primary, {"GATEWAY_COPY_URLS": "http://gw-0:4000/path"}
    )
    assert refused.misconfigured
    assert not refused.confirm("m", None).complete
    assert not refused.confirm("m", "a" * 64).complete


# GC-03 to GC-07: reading one model back from every copy.


def test_gc_03_a_lagging_copy_is_waited_for_and_every_copy_is_read_on_the_last_pass():
    store = Store()
    behind = Copy(store, lag=2)
    current = Copy(store)
    slept = []
    serving = GatewayCopies(
        [behind, current], attempts=5, pause=0.5, sleep=slept.append
    )
    store.request(
        "/api/config/resources/llm.model",
        {"value": dict(OTHER["value"], id="new", name="new")},
        "PUT",
    )
    expected = fingerprint("new", store.snapshot())
    assert serving.confirm("new", expected) == CopyReadback(2, 2)
    assert slept == [0.5, 0.5]
    assert behind.reads == current.reads == 3


@pytest.mark.parametrize("kind", ["stale", "down", "raises", "malformed"])
def test_gc_04_a_copy_that_never_confirms_leaves_the_change_unconfirmed(kind):
    store = Store()
    # A stale copy keeps serving what it had before the write.
    bad = Copy(store, stale=kind == "stale", down=kind == "down")
    store.request(
        "/api/config/resources/llm.model",
        {"value": dict(OTHER["value"], id="new", name="new")},
        "PUT",
    )
    if kind == "raises":
        bad.request = lambda *a, **k: (_ for _ in ()).throw(OSError("refused"))
    if kind == "malformed":
        bad.request = lambda *a, **k: (200, {"resources": "not-a-list"})
    result = copies_of(Copy(store), bad).confirm(
        "new", fingerprint("new", store.snapshot())
    )
    assert result == CopyReadback(2, 1)
    assert not result.complete
    assert result.summary() == "1 of 2 gateway copies confirmed it."


def test_gc_05_the_same_definition_at_another_revision_is_not_confirmed():
    store = Store()
    moved = Copy(store, stale=True)
    moved.frozen = [dict(OTHER, revision=5)]
    result = copies_of(Copy(store), moved).confirm(
        OTHER["id"], fingerprint(OTHER["id"], [OTHER])
    )
    assert result == CopyReadback(2, 1)


def test_gc_06_removal_is_confirmed_only_when_no_copy_lists_the_model():
    store = Store()
    still = Copy(store, stale=True)
    gone = Copy(store)
    store.delete_model(OTHER["id"])
    assert copies_of(gone, still).confirm(OTHER["id"], None) == CopyReadback(2, 1)
    still.stale = False
    assert copies_of(gone, still).confirm(OTHER["id"], None).complete


def test_gc_07_copy_reads_never_write_or_ask_a_model(monkeypatch):
    seen = []

    class Adapter:
        def request(self, path, body=None, method=None, **options):
            seen.append((path, body, method, options))
            return 200, {"resources": []}

    copies_of(Adapter(), Adapter()).confirm("m", None)
    assert (
        seen
        == [
            (
                copies_module.RESOURCES,
                None,
                None,
                {"timeout": 5, "connection_retries": 0},
            )
        ]
        * 2
    )


# GC-10 to GC-15: adding and editing a model.


def local_body(name="new-model"):
    return {"name": name, "model": "upstream", "source": "fixture"}


def test_gc_10_a_new_model_is_set_up_only_after_every_copy_reads_it(
    tmp_path, monkeypatch
):
    store, catalog = Store(), Catalog()
    serving = copies_of(Copy(store, lag=1), Copy(store))
    monkeypatch.setattr(
        ModelManagement,
        "confirm_new_model",
        lambda self, name, params: fingerprint(name, store.snapshot()),
    )
    status, _ = manager(store, catalog, serving, tmp_path, monkeypatch).add(
        local_body()
    )
    assert status == 200
    assert catalog.get("new-model")["gateway_fingerprint"] == fingerprint(
        "new-model", store.snapshot()
    )


def test_gc_11_a_copy_that_cannot_confirm_a_new_model_keeps_it_unavailable(
    tmp_path, monkeypatch
):
    store, catalog = Store(), Catalog()
    before_other = copy.deepcopy(catalog.rows[OTHER["id"]])
    serving = copies_of(Copy(store), Copy(store, stale=True))
    monkeypatch.setattr(
        ModelManagement,
        "confirm_new_model",
        lambda self, name, params: fingerprint(name, store.snapshot()),
    )
    status, body = manager(store, catalog, serving, tmp_path, monkeypatch).add(
        local_body()
    )
    assert status == 503
    assert body["error"] == (
        NOT_EVERY_COPY + "1 of 2 gateway copies confirmed it. Registration was removed."
    )
    assert catalog.get("new-model") is None
    assert set(store.records) == {OTHER["id"]}
    # The other model keeps its definition and its setup.
    assert store.records[OTHER["id"]] == OTHER
    assert catalog.rows[OTHER["id"]] == before_other


def test_gc_12_a_cloud_model_with_a_shared_key_is_withdrawn_with_its_key(
    tmp_path, monkeypatch
):
    store, catalog = Store(), Catalog()
    serving = copies_of(Copy(store), Copy(store, down=True))
    monkeypatch.setattr(
        ModelManagement,
        "confirm_cloud_model",
        lambda self, name, resource, **_: (fingerprint(name, store.snapshot()), None),
    )
    status, body = manager(store, catalog, serving, tmp_path, monkeypatch).add(
        {
            "name": "cloud-model",
            "model": "upstream",
            "source": "openai",
            "key_choice": "shared",
            "shared_key": "synthetic-shared-provider-key",
        }
    )
    assert status == 503
    assert body["error"].startswith(NOT_EVERY_COPY)
    assert body["error"].endswith("Nothing was saved.")
    assert catalog.get("cloud-model") is None
    assert "cloud-model" not in store.records
    assert not list((tmp_path / "keys").iterdir())


def approved_local(store, catalog, classes):
    value = dict(OTHER["value"], id="edited", name="edited")
    store.request("/api/config/resources/llm.model", {"value": value}, "PUT")
    catalog.approve(
        "edited",
        classes,
        fingerprint("edited", store.snapshot()),
        ACTOR,
        owned_by_keeplane=True,
    )
    return catalog.get("edited")


def test_gc_13_narrowing_classes_is_saved_even_when_a_copy_is_down(
    tmp_path, monkeypatch
):
    store, catalog = Store(), Catalog()
    approved_local(store, catalog, ["Public", "Internal"])
    down = Copy(store, down=True)
    management = manager(
        store, catalog, copies_of(down), tmp_path, monkeypatch, classes_on=True
    )
    status, body = management.setup(
        "edited", {"key_choice": "none", "approved_classes": ["Public"]}
    )
    assert (status, body["approved_classes"]) == (200, ["Public"])
    assert down.reads == 0


def test_gc_14_widening_classes_waits_for_every_copy_and_keeps_the_earlier_setup(
    tmp_path, monkeypatch
):
    store, catalog = Store(), Catalog()
    before = approved_local(store, catalog, ["Public"])
    widen = {"key_choice": "none", "approved_classes": ["Public", "Internal"]}
    down = Copy(store, down=True)
    management = manager(
        store,
        catalog,
        copies_of(Copy(store), down),
        tmp_path,
        monkeypatch,
        classes_on=True,
    )
    status, body = management.setup("edited", widen)
    assert status == 503
    assert body["error"] == (
        NOT_EVERY_COPY + "1 of 2 gateway copies confirmed it. Nothing was saved."
    )
    assert catalog.get("edited") == before
    down.down = False
    assert management.setup("edited", widen)[0] == 200
    assert catalog.get("edited")["approved_classes"] == ["Public", "Internal"]


def test_gc_15_a_changed_definition_is_not_approved_until_every_copy_reads_it(
    tmp_path, monkeypatch
):
    store, catalog = Store(), Catalog()
    before = approved_local(store, catalog, ["Public"])
    stale = Copy(store, stale=True)
    stale.freeze()
    # The definition changes in the gateway; one copy still serves the old one.
    store.request(
        "/api/config/resources/llm.model",
        {
            "value": dict(
                store.records["edited"]["value"],
                params={"model": "v2", "baseUrl": "http://model:18080/v1"},
            )
        },
        "PUT",
    )
    management = manager(
        store,
        catalog,
        copies_of(Copy(store), stale),
        tmp_path,
        monkeypatch,
        classes_on=True,
    )
    status, body = management.setup(
        "edited", {"key_choice": "none", "approved_classes": ["Public"]}
    )
    assert status == 503
    assert body["error"].startswith(NOT_EVERY_COPY)
    assert catalog.get("edited") == before


def test_gc_16_a_replaced_shared_key_goes_back_when_a_copy_cannot_confirm(
    tmp_path, monkeypatch
):
    store, catalog = Store(), Catalog()
    keys = tmp_path / "keys"
    keys.mkdir()
    old_key = keys / ("key-" + "b" * 32)
    old_key.write_text("synthetic-original-provider-key")
    value = {
        "id": "keyed",
        "name": "keyed",
        "provider": "openAI",
        "params": {"model": "upstream"},
        "auth": {"key": {"value": {"file": str(old_key)}}},
    }
    store.request("/api/config/resources/llm.model", {"value": value}, "PUT")
    catalog.approve(
        "keyed",
        [],
        fingerprint("keyed", store.snapshot()),
        ACTOR,
        owned_by_keeplane=True,
        key_choice="shared",
    )
    monkeypatch.setattr(
        ModelManagement,
        "confirm_cloud_model",
        lambda self, name, resource, **_: (fingerprint(name, store.snapshot()), None),
    )
    stale = Copy(store, stale=True)
    stale.freeze()
    management = manager(
        store, catalog, copies_of(Copy(store), stale), tmp_path, monkeypatch
    )
    status, body = management.setup(
        "keyed",
        {"key_choice": "shared", "replace_shared_key": "synthetic-replacement-key"},
    )
    assert status == 503
    assert body["error"] == (
        NOT_EVERY_COPY
        + "1 of 2 gateway copies confirmed it. The previous key is still active."
    )
    assert store.records["keyed"]["value"] == value
    assert sorted(path.name for path in keys.iterdir()) == [old_key.name]


# GC-20 to GC-22: removing a model.


def owned(store, catalog, key_file=None):
    value = dict(OTHER["value"], id="gone", name="gone")
    if key_file:
        value["auth"] = {"key": {"value": {"file": str(key_file)}}}
    store.request("/api/config/resources/llm.model", {"value": value}, "PUT")
    catalog.approve(
        "gone",
        ["Public"],
        fingerprint("gone", store.snapshot()),
        ACTOR,
        owned_by_keeplane=True,
        key_choice="shared" if key_file else "none",
    )


def test_gc_20_removal_is_acknowledged_after_every_copy_reads_it_gone():
    store, catalog = Store(), Catalog()
    owned(store, catalog)
    serving = copies_of(Copy(store, lag=1), Copy(store))
    status, body = remove_model_setup("gone", ACTOR, catalog, store, None, "", serving)
    assert (status, body) == (
        200,
        {"removed_from_keeplane": True, "gateway_model_preserved": False},
    )
    assert set(store.records) == {OTHER["id"]}


def test_gc_21_a_copy_still_listing_the_model_is_reported_and_the_model_stays_withdrawn(
    tmp_path,
):
    store, catalog = Store(), Catalog()
    key = tmp_path / ("key-" + "c" * 32)
    key.write_text("synthetic-shared-provider-key")
    owned(store, catalog, key)
    stale = Copy(store, stale=True)
    stale.freeze()
    serving = copies_of(Copy(store), stale)
    status, body = remove_model_setup(
        "gone", ACTOR, catalog, store, None, str(tmp_path), serving
    )
    assert status == 503
    assert body["error"] == NOT_GONE_EVERYWHERE.format(
        summary="1 of 2 gateway copies confirmed it."
    )
    # The withdrawal is kept: no approval and no key for the stale copy to use.
    assert catalog.get("gone") is None
    assert not key.exists()
    assert catalog.get(OTHER["id"]) is not None


def test_gc_22_removing_a_customer_added_model_reads_no_copy():
    store, catalog = Store(), Catalog()
    catalog.rows[OTHER["id"]]["owned_by_keeplane"] = False
    reader = Copy(store, down=True)
    status, body = remove_model_setup(
        OTHER["id"], ACTOR, catalog, store, None, "", copies_of(reader)
    )
    assert (status, body["gateway_model_preserved"]) == (200, True)
    assert reader.reads == 0
    assert store.records[OTHER["id"]] == OTHER


def test_gc_23_without_listed_copies_the_gateway_address_alone_confirms(
    tmp_path, monkeypatch
):
    store, catalog = Store(), Catalog()
    monkeypatch.setattr(
        ModelManagement,
        "confirm_new_model",
        lambda self, name, params: fingerprint(name, store.snapshot()),
    )
    assert (
        manager(store, catalog, None, tmp_path, monkeypatch).add(local_body())[0] == 200
    )
    owned(store, catalog)
    assert remove_model_setup("gone", ACTOR, catalog, store, None, "")[0] == 200
