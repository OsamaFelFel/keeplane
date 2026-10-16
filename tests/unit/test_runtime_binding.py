"""Changing a disjoint exact model must not renew another model's binding."""

from copy import deepcopy
from types import SimpleNamespace

import pytest
from integrations.gateway.runtime_binding import (
    model_serving_binding,
    read_model_binding,
)
from integrations.gateway.runtime_config import RuntimeInstallationUnavailable, overlay

from integrations.gateway import runtime_binding
from tests.unit.test_applied_gateway import dump
from tests.unit.test_runtime_readback import fixture as provider_fixture


def snapshot():
    native, resources = provider_fixture()
    resources[0].update(id="demo", kind="llm.model", revision=1)
    native["backends"][0]["backend"]["ai"]["namespace"] = ""
    native["backends"][0]["backend"]["ai"]["target"]["providers"][0]["active"]["demo"][
        "info"
    ] = deepcopy(
        dump()["backends"][0]["backend"]["ai"]["target"]["providers"][0]["active"][
            "model"
        ]["info"]
    )
    native["backends"][0]["inlinePolicies"] = [{"ai": {}}]
    applied = dump()
    applied["backends"] = native["backends"]
    route = {
        "id": "demo",
        "name": "demo",
        "created": 123,
        "visibility": "public",
        "headerMatches": [],
        "backend": {"weight": 1, "backend": "/llm:model:demo"},
        "policies": {"llm": {}, "authorization": None},
        "backendPolicies": [],
    }
    applied["backends"].append(
        {
            "backend": {
                "llmRouter": {
                    "name": "llm:router",
                    "namespace": "",
                    "target": {"discovery": {}, "models": [route], "virtualModels": []},
                }
            }
        }
    )
    base = {
        "config": {},
        "gateways": {"default": {"port": 4000}},
        "llm": {
            "models": [],
            "policies": {
                "apiKey": {"mode": "strict", "keys": [{"keyHash": "synthetic"}]}
            },
        },
    }
    config = overlay(
        base,
        {"demo": {"fingerprint": "a" * 64, "key_choice": "none"}},
        {"demo": "llm:model:demo"},
    )
    applied["binds"] = deepcopy(config["binds"])
    applied["policies"] = [
        {"key": "/" + row["name"]["name"], **deepcopy(row)}
        for row in config["policies"]
    ]
    return {
        "file_config": config,
        "effective_config": effective(config, resources),
        "resources": resources,
        "applied": applied,
    }


def effective(config, resources):
    result = deepcopy(config)
    result["llm"]["models"].extend(deepcopy([row["value"] for row in resources]))
    return result


def binding(state):
    return model_serving_binding("demo", "none", **state)


def router(state):
    return state["applied"]["backends"][-1]["backend"]["llmRouter"]["target"]


def add_other(state):
    resource = deepcopy(state["resources"][0])
    resource["id"] = resource["value"]["id"] = resource["value"]["name"] = "aaa-before"
    state["resources"].insert(0, resource)
    state["effective_config"] = effective(state["file_config"], state["resources"])
    route = deepcopy(router(state)["models"][0])
    route.update(
        id="aaa-before",
        name="aaa-before",
        backend={"weight": 1, "backend": "/llm:model:aaa-before"},
    )
    router(state)["models"].insert(0, route)
    backend = deepcopy(state["applied"]["backends"][0])
    backend["backend"]["ai"]["name"] = "llm:model:aaa-before"
    group = backend["backend"]["ai"]["target"]["providers"][0]
    group["active"]["aaa-before"] = group["active"].pop("demo")
    group["active"]["aaa-before"]["endpoint"]["name"] = "aaa-before"
    state["applied"]["backends"].insert(0, backend)
    target = {"backend": {"backend": {"name": "llm:model:aaa-before", "namespace": ""}}}
    policy = {
        "name": {"name": "other-final", "namespace": ""},
        "target": target,
        "policy": {"extAuthz": {"host": "private:3000"}},
    }
    state["file_config"]["policies"].append(deepcopy(policy))
    state["effective_config"] = effective(state["file_config"], state["resources"])
    state["applied"]["policies"].append({"key": "/other-final", **policy})


def test_safe_other_model_add_edit_remove_and_partial_propagation_keep_binding():
    state = snapshot()
    original, untouched = binding(state), deepcopy(state)
    assert state == untouched
    add_other(state)
    assert binding(state) == original
    # The other copy can be between its resource and applied updates.
    state["resources"][0]["revision"] += 1
    state["resources"][0]["value"]["params"]["baseUrl"] = "https://changed.invalid/v1"
    assert binding(state) == original
    state["effective_config"] = effective(state["file_config"], state["resources"])
    state["applied"]["backends"][0]["backend"]["ai"]["target"]["providers"][0][
        "active"
    ]["aaa-before"]["endpoint"]["hostOverride"] = "changed.invalid:443"
    assert binding(state) == original
    state["resources"].pop(0)
    state["effective_config"] = effective(state["file_config"], state["resources"])
    assert binding(state) == original
    router(state)["models"].pop(0)
    state["applied"]["backends"].pop(0)
    state["applied"]["policies"].pop()
    state["file_config"]["policies"].pop()
    state["effective_config"] = effective(state["file_config"], state["resources"])
    assert binding(state) == original


@pytest.mark.parametrize(
    "change",
    [
        "revision",
        "entry",
        "raw",
        "final",
        "strip",
        "private",
        "unknown",
        "health-policy",
        "key-file",
    ],
)
def test_selected_or_shared_change_is_bound(change):
    state = snapshot()
    before = binding(state)
    if change == "revision":
        state["resources"][0]["revision"] += 1
    elif change == "entry":
        state["file_config"]["binds"][0]["listeners"][0]["routes"][0]["policies"][
            "extAuthz"
        ]["failureMode"] = "allow"
        state["effective_config"] = effective(state["file_config"], state["resources"])
    elif change == "raw":
        state["applied"]["config"]["adminAddr"] = "0.0.0.0:15000"
    elif change in ("final", "strip"):
        state["applied"]["policies"][0 if change == "final" else 1]["policy"][
            "changed"
        ] = True
    elif change == "private":
        state["applied"]["routes"]["private-applied"] = {"target": "outside:15000"}
    elif change == "unknown":
        state["applied"]["backends"][0]["extra"] = True
    elif change == "health-policy":
        state["applied"]["config"]["backend"] = {"health": {"eviction": 1}}
    else:
        state["resources"][0]["value"]["auth"] = {
            "key": {"value": {"file": "/provider-keys/different"}}
        }
        state["effective_config"] = effective(state["file_config"], state["resources"])
    assert binding(state) != before


@pytest.mark.parametrize(
    "change",
    [
        "destination",
        "auth",
        "target",
        "wildcard",
        "legacy",
        "headers",
        "virtual",
        "unknown-route",
        "unknown-target",
        "global-api-policy",
        "duplicate",
        "namespace",
    ],
)
def test_ambiguous_or_changed_selected_dispatch_is_refused(change):
    state = snapshot()
    if change in ("destination", "auth"):
        row = state["applied"]["backends"][0]
        if change == "auth":
            row["inlinePolicies"].insert(
                0, {"backendAuth": {"key": {"value": "<redacted>"}}}
            )
        else:
            row["backend"]["ai"]["target"]["providers"][0]["active"]["demo"][
                "endpoint"
            ]["hostOverride"] = "outside:443"
    elif change == "target":
        router(state)["models"][0]["backend"]["backend"] = "/llm:model:other"
    elif change == "virtual":
        router(state)["virtualModels"].append({"name": "demo"})
    elif change == "unknown-target":
        state["applied"]["policies"][0]["target"] = {"future": {"model": "other"}}
    elif change == "global-api-policy":
        state["resources"].append(
            {"kind": "llm.policy", "id": "auth", "value": {}, "revision": 1}
        )
    elif change == "duplicate":
        router(state)["models"].append(deepcopy(router(state)["models"][0]))
    elif change == "namespace":
        state["applied"]["policies"][0]["target"]["backend"]["backend"]["namespace"] = (
            "other"
        )
    else:
        add_other(state)
        row = router(state)["models"][0]
        if change == "wildcard":
            row["name"] = "*"
        elif change == "legacy":
            del row["id"]
        elif change == "headers":
            row["headerMatches"] = [[{"name": "x-model", "value": "demo"}]]
        else:
            row["future-selector"] = "demo"
    with pytest.raises(RuntimeInstallationUnavailable, match="binding is unavailable"):
        binding(state)


def test_measurements_only_are_excluded_and_inputs_are_not_changed():
    state = snapshot()
    before = binding(state)
    info = state["applied"]["backends"][0]["backend"]["ai"]["target"]["providers"][0][
        "active"
    ]["demo"]["info"]
    info.update(health=0.7, consecutiveFailures=1, totalRequests=10)
    copy = deepcopy(state)
    assert binding(state) == before and state == copy
    info["timesEjected"] = 1
    assert binding(state) != before


@pytest.mark.parametrize("failure", [None, "file", "resources", "applied"])
def test_reads_configured_copy_and_refuses_unavailable_snapshots(monkeypatch, failure):
    state, calls = snapshot(), []
    values = {
        "/api/config": state["file_config"],
        "/api/config/effective": state["effective_config"],
        "/api/config/resources": {"resources": state["resources"]},
    }

    def request(path, **options):
        calls.append((path, options))
        if failure == "file" and path == "/api/config":
            return 503, {"error": "private-diagnostic-must-not-be-reflected"}
        if failure == "resources" and path.endswith("resources"):
            return 200, {"resources": []}
        return 200, values[path]

    gateway = SimpleNamespace(request=request)

    def applied(configured):
        assert configured is gateway
        if failure == "applied":
            raise OSError("private-diagnostic-must-not-be-reflected")
        return state["applied"]

    monkeypatch.setattr(runtime_binding, "read_applied", applied)
    if failure:
        with pytest.raises(RuntimeInstallationUnavailable) as caught:
            read_model_binding(gateway, "demo", "none")
        assert str(caught.value) == "The model serving binding is unavailable"
    else:
        assert read_model_binding(gateway, "demo", "none") == binding(state)
        assert [path for path, _ in calls] == list(values)
    assert all(
        options == {"timeout": 5, "connection_retries": 0} for _, options in calls
    )
