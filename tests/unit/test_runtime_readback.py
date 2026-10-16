"""Reject a compiled provider that differs from the approved raw definition."""

from copy import deepcopy

import pytest
from integrations.gateway.runtime_config import RuntimeInstallationUnavailable
from integrations.gateway.runtime_readback import require_applied_models


def fixture():
    resources = [
        {
            "id": "demo",
            "value": {
                "id": "demo",
                "name": "demo",
                "provider": "openAI",
                "params": {"model": "upstream", "baseUrl": "http://provider:18080/v1"},
            },
        }
    ]
    endpoint = {
        "name": "demo",
        "provider": {"openAI": {"model": "upstream"}},
        "hostOverride": "provider:18080",
        "pathOverride": None,
        "pathPrefix": "/v1",
        "tokenize": False,
    }
    dump = {
        "backends": [
            {
                "backend": {
                    "ai": {
                        "name": "llm:model:demo",
                        "target": {
                            "providers": [
                                {
                                    "active": {
                                        "demo": {
                                            "endpoint": endpoint,
                                            "capacity": 1,
                                            "info": {},
                                        }
                                    },
                                    "rejected": {},
                                }
                            ]
                        },
                    }
                },
                "inlinePolicies": [
                    {"backendAuth": {"key": {"value": "<redacted>"}}},
                    {"ai": {}},
                ],
            }
        ]
    }
    return dump, resources


def verify(dump, resources):
    require_applied_models(
        dump, resources, {"demo": {"key_choice": "shared"}}, {"demo": "llm:model:demo"}
    )


def test_applied_provider_matches_approved_upstream_without_key_readback():
    dump, resources = fixture()
    verify(dump, resources)
    assert "<redacted>" in str(dump) and "auth" not in resources[0]["value"]


@pytest.mark.parametrize(
    "fault",
    [
        "endpoint",
        "model",
        "provider",
        "path",
        "tokenize",
        "auth",
        "policy",
        "capacity",
        "duplicate",
        "extra-provider",
        "fallback",
        "rejected",
    ],
)
def test_changed_or_ambiguous_provider_cannot_activate(fault):
    dump, resources = fixture()
    row = dump["backends"][0]
    providers = row["backend"]["ai"]["target"]["providers"]
    active = providers[0]["active"]["demo"]
    endpoint = active["endpoint"]
    if fault == "endpoint":
        endpoint["hostOverride"] = "another-provider:18080"
    elif fault == "model":
        endpoint["provider"]["openAI"]["model"] = "different-upstream"
    elif fault == "provider":
        endpoint["provider"] = {"anthropic": {"model": "upstream"}}
    elif fault == "path":
        endpoint["pathPrefix"] = "/outside"
    elif fault == "tokenize":
        endpoint["tokenize"] = True
    elif fault == "auth":
        row["inlinePolicies"].pop(0)
    elif fault == "policy":
        row["inlinePolicies"].append(
            {"requestHeaders": {"set": {"x-client-key": "forged"}}}
        )
    elif fault == "capacity":
        active["capacity"] = 2
    elif fault == "duplicate":
        dump["backends"].append(deepcopy(row))
    elif fault == "extra-provider":
        providers[0]["active"]["outside"] = deepcopy(active)
    elif fault == "fallback":
        providers.append(deepcopy(providers[0]))
    else:
        providers[0]["rejected"]["outside"] = deepcopy(active)
    with pytest.raises(RuntimeInstallationUnavailable):
        verify(dump, resources)
