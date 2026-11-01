"""Each copy's guard names its copy; the app finds that copy's address (ADR 027).

Cases GS-U01 to GS-U05 in tests/integration/guard-status-cases.md.
"""

import json
from types import SimpleNamespace

import pytest
from integrations.gateway.runtime_config import (
    RuntimeInstallationUnavailable,
    callback_copies,
    model_backends,
    overlay,
)
from model_registry.guard_status import copy_gateway
from model_registry.policy import ModelPolicyUnavailable

from tests.unit.test_runtime_config import applied

BASE = {
    "config": {},
    "gateways": {"default": {"port": 4000}},
    "llm": {"policies": {"apiKey": {"mode": "strict", "keys": [{"keyHash": "x"}]}}},
}
MODELS = {
    "demo": {"fingerprint": "a" * 64, "key_choice": "none"},
    "own": {"fingerprint": "b" * 64, "key_choice": "personal"},
}


def guard(**options):
    dump = applied()
    rows = dump["backends"][0]["backend"]["llmRouter"]["target"]["models"]
    rows.append(
        {"name": "own", "backend": {"backend": "/llm:model:own"}, "headerMatches": []}
    )
    return overlay(
        BASE,
        MODELS,
        model_backends(dump, list(MODELS)),
        personal_providers={"own": "openAI"},
        **options,
    )


def bodies(config):
    route = config["binds"][-1]["listeners"][0]["routes"][0]
    entry = route["policies"]["extAuthz"]["protocol"]["http"]["body"]
    selected = [
        row["policy"]["extAuthz"]["protocol"]["http"]["body"]
        for row in config["policies"]
        if "extAuthz" in row["policy"]
    ]
    exchange = [
        row["policy"]["backendAuth"]["oauthTokenExchange"]["additionalParams"]
        for row in config["policies"]
        if "backendAuth" in row["policy"]
    ]
    return entry, selected, exchange


def test_gs_u01_every_protected_check_names_the_copy():
    entry, selected, exchange = bodies(guard(gateway_copy="keeplane-gateway-1"))
    field = '"gateway_copy": "keeplane-gateway-1"'
    assert field in entry
    for body in selected:
        protected, operator = body.split(
            ' : request.headers["x-keeplane-installed-runtime"]', 1
        )
        assert field in protected
        # Operator validation attests no enrolment and names no copy.
        assert "gateway_copy" not in operator
    assert exchange and all(
        json.loads(row["gateway_copy"]) == "keeplane-gateway-1" for row in exchange
    )


def test_gs_u02_the_docker_preview_guard_is_unchanged():
    entry, selected, exchange = bodies(guard())
    assert "gateway_copy" not in entry
    assert all("gateway_copy" not in body for body in selected)
    assert all("gateway_copy" not in row for row in exchange)
    assert guard() == guard(gateway_copy=None)


@pytest.mark.parametrize(
    "name",
    ["", "Keeplane-0", "-gateway", "gateway-", 'gw"0', "gw 0", "a" * 64, 7, "gw.0"],
)
def test_gs_u03_a_copy_name_that_is_not_a_pod_name_is_refused(name):
    with pytest.raises(RuntimeInstallationUnavailable, match="copy name"):
        guard(gateway_copy=name)


def test_gs_u04_the_enroller_reads_which_copy_a_guard_names():
    assert callback_copies(guard(gateway_copy="keeplane-gateway-0")) == {
        "keeplane-gateway-0"
    }
    assert callback_copies(guard()) == {None}
    mixed = guard(gateway_copy="keeplane-gateway-0")
    other = guard(gateway_copy="keeplane-gateway-1")
    mixed["policies"][0] = other["policies"][0]
    assert callback_copies(mixed) == {"keeplane-gateway-0", "keeplane-gateway-1"}
    assert callback_copies({"policies": [{"policy": None}]}) is None


def copies(*urls, misconfigured=False):
    return SimpleNamespace(
        copies=[SimpleNamespace(base_url=url) for url in urls],
        misconfigured=misconfigured,
    )


def test_gs_u05_the_app_reads_only_the_named_copy_address():
    listed = copies(
        "http://keeplane-gateway-1.keeplane-gateway-copies.team.svc:4000",
        "http://keeplane-gateway-10.keeplane-gateway-copies.team.svc:4000",
        "http://keeplane-gateway-0.keeplane-gateway-copies.team.svc:4000",
    )
    assert copy_gateway("keeplane-gateway-1", listed) is listed.copies[0]
    assert copy_gateway("keeplane-gateway-10", listed) is listed.copies[1]
    for name in ("keeplane-gateway", "keeplane-gateway-2", "Keeplane-gateway-0", None):
        with pytest.raises(ModelPolicyUnavailable):
            copy_gateway(name, listed)
    twice = copies(
        "http://gw-0.a.svc:4000",
        "http://gw-0.b.svc:4000",
    )
    with pytest.raises(ModelPolicyUnavailable):
        copy_gateway("gw-0", twice)
    with pytest.raises(ModelPolicyUnavailable):
        copy_gateway("gw-0", copies("http://gw-0.a.svc:4000", misconfigured=True))
