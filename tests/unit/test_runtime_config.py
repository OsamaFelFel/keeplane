"""Use actual applied native model references without changing raw resources."""

from copy import deepcopy

import pytest
from integrations.gateway.runtime_config import (
    RuntimeInstallationUnavailable,
    model_backends,
    overlay,
)


def applied():
    # Pinned standalone config_dump keeps routes inside the router backend,
    # not its top-level models array. A name-only model has an indexed target.
    return {
        "models": [],
        "backends": [
            {
                "backend": {
                    "llmRouter": {
                        "name": "llm:router",
                        "namespace": "",
                        "target": {
                            "models": [
                                {
                                    "name": "demo",
                                    "backend": {"backend": "/llm:model:demo"},
                                    "headerMatches": [],
                                }
                            ],
                            "virtualModels": [],
                        },
                    }
                }
            }
        ],
    }


def test_stable_models_keep_raw_configuration_and_existing_operator_auth():
    base = {
        "config": {},
        "gateways": {"default": {"port": 4000}},
        "ui": {"gateways": "default"},
        "llm": {"models": [{"name": "customer-owned"}]},
    }
    base["llm"]["policies"] = {
        "apiKey": {"mode": "strict", "keys": [{"keyHash": "sha256:" + "a" * 64}]},
    }
    original = deepcopy(base)
    targets = model_backends(applied(), ["demo"])
    assert targets == {"demo": "llm:model:demo"}
    result = overlay(
        base, {"demo": {"fingerprint": "a" * 64, "key_choice": "none"}}, targets
    )
    assert base == original and result["llm"] == base["llm"]
    assert result["ui"] == base["ui"]
    assert result["gateways"]["default"]["port"] == 4000
    assert {
        row["target"]["backend"]["backend"]["name"] for row in result["policies"]
    } == {"llm:model:demo"}


def test_pd_11_both_request_checks_carry_the_messages():
    """Spec 005 ST20: detection needs the request text at entry and final check."""
    base = {
        "config": {},
        "gateways": {"default": {"port": 4000}},
        "llm": {"policies": {"apiKey": {"mode": "strict", "keys": [{"keyHash": "x"}]}}},
    }
    result = overlay(
        base,
        {"demo": {"fingerprint": "a" * 64, "key_choice": "none"}},
        model_backends(applied(), ["demo"]),
    )
    messages = '"messages": json(request.body).messages'
    route = result["binds"][-1]["listeners"][0]["routes"][0]
    entry = route["policies"]["extAuthz"]["protocol"]["http"]["body"]
    assert messages in entry and '"model_id": json(request.body).model' in entry
    selected = next(
        row["policy"]["extAuthz"]["protocol"]["http"]["body"]
        for row in result["policies"]
        if "extAuthz" in row["policy"]
    )
    protected, operator = selected.split(" : ", 1)
    assert messages in protected
    assert "messages" not in operator


@pytest.mark.parametrize(
    "fault",
    ["missing", "virtual", "duplicate", "conditional", "different-id", "indexed"],
)
def test_ambiguous_or_nonconcrete_applied_routes_are_not_installed(fault):
    dump = applied()
    rows = dump["backends"][0]["backend"]["llmRouter"]["target"]["models"]
    if fault == "missing":
        rows.clear()
    elif fault == "virtual":
        rows[0]["backend"]["backend"] = "/llm:virtual-model:demo:0"
    elif fault == "duplicate":
        rows.append(deepcopy(rows[0]))
    elif fault == "conditional":
        rows[0]["headerMatches"] = [{"name": "untrusted"}]
    elif fault == "indexed":
        rows[0]["backend"]["backend"] = "/llm:model:demo:3"
    else:
        rows[0]["id"] = "different"
    with pytest.raises(RuntimeInstallationUnavailable):
        model_backends(dump, ["demo"])


def test_an_existing_listener_is_not_overwritten():
    with pytest.raises(RuntimeInstallationUnavailable, match="already configured"):
        overlay(
            {
                "gateways": {"default": {"port": 4000}},
                "binds": [{"port": 5000}],
                "llm": {
                    "policies": {
                        "apiKey": {
                            "mode": "strict",
                            "keys": [{"keyHash": "sha256:" + "a" * 64}],
                        }
                    }
                },
            },
            {"demo": {"fingerprint": "a" * 64, "key_choice": "none"}},
            {"demo": "llm:model:demo"},
        )


def test_adding_personal_policy_preserves_existing_operator_and_shared_guards():
    base = {
        "gateways": {"default": {"port": 4000}},
        "llm": {"policies": {"apiKey": {"mode": "strict", "keys": [{"keyHash": "a"}]}}},
    }
    shared = {"demo": {"fingerprint": "b" * 64, "key_choice": "shared"}}
    before = overlay(base, shared, {"demo": "llm:model:demo"})
    after = overlay(
        base,
        {**shared, "personal": {"fingerprint": "a" * 64, "key_choice": "personal"}},
        {"demo": "llm:model:demo", "personal": "llm:model:personal"},
        personal_providers={"personal": "openAI"},
    )
    assert all(policy in after["policies"] for policy in before["policies"])
    assert before["gateways"] == after["gateways"]
    assert before["binds"] == after["binds"] and before["llm"] == after["llm"]
    assert sum("backendAuth" in policy["policy"] for policy in after["policies"]) == 1


@pytest.mark.parametrize(
    "provider,header", [("openAI", "authorization"), ("anthropic", "x-api-key")]
)
def test_personal_provider_auth_location_matches_the_validated_raw_provider(
    provider, header
):
    base = {
        "gateways": {"default": {"port": 4000}},
        "llm": {"policies": {"apiKey": {"mode": "strict", "keys": [{"keyHash": "a"}]}}},
    }
    result = overlay(
        base,
        {"demo": {"fingerprint": "a" * 64, "key_choice": "personal"}},
        {"demo": "llm:model:demo"},
        personal_providers={"demo": provider},
    )
    exchange = next(
        row["policy"]["backendAuth"]["oauthTokenExchange"]
        for row in result["policies"]
        if "backendAuth" in row["policy"]
    )
    location = exchange.get(
        "authorizationLocation",
        {"header": {"name": "authorization", "prefix": "Bearer "}},
    )
    assert location["header"]["name"] == header
    if provider == "anthropic":
        assert (
            location["header"]["prefix"] == ""
            and header in result["config"]["sensitiveHeaders"]
        )
    strip = next(
        row["policy"]["transformations"]["request"]["replace"]
        for row in result["policies"]
        if "transformations" in row["policy"]
    )
    assert (
        strip
        == '{"content-type": "application/json", "'
        + header
        + '": request.headers["'
        + header
        + '"]}'
    )


@pytest.mark.parametrize(
    "providers", [None, {}, {"demo": "custom"}, {"other": "anthropic"}]
)
def test_personal_provider_map_cannot_be_inferred_or_mismatched(providers):
    with pytest.raises(RuntimeInstallationUnavailable):
        overlay(
            {},
            {"demo": {"key_choice": "personal"}},
            {"demo": "llm:model:demo"},
            personal_providers=providers,
        )
