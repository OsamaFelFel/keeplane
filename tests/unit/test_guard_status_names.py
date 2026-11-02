"""Each copy's guard names its copy; the app finds that copy's address (ADR 027).

Cases GS-U01 to GS-U07 in tests/integration/guard-status-cases.md.
"""

import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from integrations.gateway.runtime_config import (
    RuntimeInstallationUnavailable,
    callback_copies,
    model_backends,
    overlay,
)
from common import credential_check
from model_registry import guard_status_access as access
from model_registry.guard_status import copy_gateway
from model_registry.models import GatewayGuardStatus
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


def printed(*pairs, column="(copy_name)::text"):
    """An own-copy condition as PostgreSQL prints it back from pg_policies."""
    values = ", ".join(f"('{name}'::text,'{role}'::text)" for name, role in pairs)
    return f"(({column}, (CURRENT_USER)::text) IN ( VALUES {values}))"


PAIRS = (("keeplane-gateway-0", "status_0"), ("keeplane-gateway-1", "status_1"))
APP_READ = ("SELECT", {"app"}, "true", "", "PERMISSIVE")


def as_set(using=None, check=None, roles=None, command="ALL", app=APP_READ,
           kind="PERMISSIVE", **more):
    using = printed(*PAIRS) if using is None else using
    return {
        access.APP_READ_POLICY: app,
        access.OWN_COPY_POLICY: (
            command,
            {"status_0", "status_1"} if roles is None else roles,
            using,
            using if check is None else check,
            kind,
        ),
        **more,
    }


def test_gs_u06_check_credentials_reads_the_pairs_the_command_set():
    assert access.policy_pairs(as_set(), "app") == dict(PAIRS)
    # Without the cast, as a text column would print it.
    plain = printed(*PAIRS, column="copy_name")
    assert access.policy_pairs(as_set(plain), "app") == dict(PAIRS)
    # The condition the command writes is the one read back.
    assert access.own_row_condition(PAIRS) == (
        "(copy_name, current_user::text) IN (VALUES "
        "('keeplane-gateway-0', 'status_0'), ('keeplane-gateway-1', 'status_1'))"
    )


@pytest.mark.parametrize(
    "changed",
    [
        {"check": printed(PAIRS[0])},  # writes allowed for fewer pairs than reads
        {"using": printed(*PAIRS) + " OR true"},
        {"using": "true", "check": "true"},
        {"roles": {"status_0", "status_1", "other"}},
        {"command": "SELECT"},
        {"kind": "RESTRICTIVE"},
        {"using": printed(PAIRS[0], ("keeplane-gateway-1", "status_0"))},
        {"using": printed(PAIRS[0], ("keeplane-gateway-0", "status_1"))},
        {"app": ("SELECT", {"app", "status_0"}, "true", "", "PERMISSIVE")},
        {"app": ("ALL", {"app"}, "true", "true", "PERMISSIVE")},
        {"app": ("SELECT", {"app"}, "true", "", "RESTRICTIVE")},
        {"anyone": ("ALL", {"status_0"}, "true", "true", "PERMISSIVE")},
    ],
)
def test_gs_u06_a_changed_policy_is_not_read_as_set(changed):
    assert access.policy_pairs(as_set(**changed), "app") is None


def test_gs_u06_the_app_read_policy_must_name_this_app_role():
    assert access.policy_pairs(as_set(), "another_app") is None
    assert access.policy_pairs({}, "app") is None


ORDINARY = {
    "powerful": False,
    "in_owner": False,
    "can_login": True,
    "password_expired": False,
    "can_connect": True,
}


def test_gs_u07_a_paired_role_that_does_not_exist_is_reported_missing():
    """The policy names status_1, but no such role exists any more."""
    copies = [SimpleNamespace(base_url=f"http://{name}.gateway:15000") for name, _ in PAIRS]
    asked = {}

    def memberships(cursor, listed):
        asked["memberships"] = list(listed)
        return []

    def extra_privileges(cursor, allowed):
        asked["extra"] = sorted(allowed)
        return []

    rows = SimpleNamespace(filter=lambda **_: [])
    with patch.multiple(
        access,
        table_owner=lambda cursor: ("app", "public", "owner"),
        policies=lambda cursor: as_set(),
        row_security=lambda cursor: True,
        role_attributes=lambda cursor, roles, owner: {
            name: dict(ORDINARY) for name in roles if name != "status_1"
        },
        read_only_roles=lambda cursor, roles: set(roles),
        memberships=memberships,
        extra_privileges=extra_privileges,
        missing_status_writes=lambda cursor, roles: [],
    ), patch.object(GatewayGuardStatus, "objects", rows):
        report, problems, warnings = credential_check._guard_status(
            None, copies, datetime(2026, 11, 2, tzinfo=timezone.utc)
        )
    # Only existing roles reach the catalog functions that need them.
    assert asked == {"memberships": ["app", "status_0"], "extra": ["app", "status_0"]}
    first, second = report["copies"]
    assert (first["role_status"], second["role_status"]) == ("limited", "missing")
    assert problems == [
        "Gateway copy keeplane-gateway-0: its enroller has recorded no guard status yet",
        "Gateway copy keeplane-gateway-1: its status role status_1 doesn't exist; "
        "ask your database operator to create it",
        "Gateway copy keeplane-gateway-1: its enroller has recorded no guard status yet",
    ]
    assert warnings == []
