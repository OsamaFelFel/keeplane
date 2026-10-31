"""Spec 004 ST16: the managed gateway retries a down model, and only that model."""

from copy import deepcopy

import pytest
from integrations.gateway.runtime_config import (
    RETRY_ATTEMPTS,
    RETRY_CODES,
    RuntimeInstallationUnavailable,
    model_backends,
    outage_retry,
    overlay,
)
from integrations.gateway.runtime_readback import compiled_callback, route_guard

from tests.unit.test_runtime_config import applied


def installed():
    base = {
        "config": {},
        "gateways": {"default": {"port": 4000}},
        "llm": {
            "models": [],
            "policies": {
                "apiKey": {"mode": "strict", "keys": [{"keyHash": "sha256:" + "a" * 64}]}
            },
        },
    }
    return overlay(
        base,
        {"demo": {"fingerprint": "a" * 64, "key_choice": "none"}},
        model_backends(applied(), ["demo"]),
    )


def protected_route(config):
    return config["binds"][-1]["listeners"][0]["routes"][0]


def test_the_protected_route_retries_the_same_model_twice():
    policies = protected_route(installed())["policies"]
    assert policies["retry"] == {
        "attempts": 2,
        "codes": [429, 500, 502, 503, 504],
        "backoff": "500ms",
    }
    assert RETRY_ATTEMPTS == 2 and set(RETRY_CODES) == {429, 500, 502, 503, 504}


def test_each_attempt_has_its_own_time_limit_before_the_answer_starts():
    # backendRequestTimeout covers each attempt up to the response headers and
    # never cuts a stream that has started.
    timeout = protected_route(installed())["policies"]["timeout"]
    assert set(timeout) == {"backendRequestTimeout"}
    assert timeout["backendRequestTimeout"].endswith("s")


def test_a_context_length_refusal_is_not_retried():
    # Providers refuse a task that is too big with a 4xx other than 429.
    assert 400 not in RETRY_CODES and 413 not in RETRY_CODES
    assert all(code == 429 or code >= 500 for code in RETRY_CODES)


def test_retry_keeps_the_entry_check_and_adds_no_other_model():
    config = installed()
    route = protected_route(config)
    assert route["backends"] == [{"backend": "llm:router"}]
    assert "extAuthz" in route["policies"]
    # No failover group or virtual model: Keeplane never switches for an outage.
    text = repr(config)
    assert "virtual-model" not in text and "failover" not in text.lower()
    # The selected-model check stays on the model backend, so every retry is
    # checked again before the provider is contacted.
    selected = [
        row for row in config["policies"] if "extAuthz" in row["policy"]
    ]
    assert [row["target"]["backend"]["backend"]["name"] for row in selected] == [
        "llm:model:demo"
    ]


def test_the_policy_is_a_fresh_copy():
    first = outage_retry()
    first["retry"]["codes"].append(400)
    assert 400 not in outage_retry()["retry"]["codes"]


def served(config):
    entry = compiled_callback(protected_route(config)["policies"]["extAuthz"])
    return entry, [
        {"extAuthz": entry},
        {"retry": {"attempts": 2, "backoff": "0.5s", "codes": [429, 500, 502, 503, 504]}},
        {"timeout": {"requestTimeout": None, "backendRequestTimeout": "60s"}},
    ]


def test_applied_route_with_the_retry_is_accepted_in_any_order():
    entry, inline = served(installed())
    assert route_guard(inline, entry) == [{"extAuthz": entry}]
    assert route_guard(list(reversed(inline)), entry) == [{"extAuthz": entry}]


@pytest.mark.parametrize(
    "fault",
    ["no-retry", "no-timeout", "other-count", "extra", "duplicate", "entry", "shape"],
)
def test_applied_route_without_the_exact_retry_is_refused(fault):
    entry, inline = served(installed())
    inline = deepcopy(inline)
    if fault == "no-retry":
        inline.pop(1)
    elif fault == "no-timeout":
        inline.pop(2)
    elif fault == "other-count":
        inline[1]["retry"]["attempts"] = 3
    elif fault == "extra":
        inline.append({"transformations": {}})
    elif fault == "duplicate":
        inline.append(deepcopy(inline[1]))
    elif fault == "entry":
        inline[0]["extAuthz"] = dict(entry, failureMode="allow")
    else:
        inline[1] = {"retry": inline[1]["retry"], "timeout": {}}
    with pytest.raises(RuntimeInstallationUnavailable):
        route_guard(inline, entry)
