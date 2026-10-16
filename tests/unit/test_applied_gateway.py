"""Read private applied state without redirects, unbounded bodies or caller keys."""

import io
import json
import secrets
import threading
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from urllib.error import HTTPError

import pytest
from integrations.gateway.applied import (
    MAX_APPLIED_BYTES,
    AppliedStateUnavailable,
    applied_fingerprint,
    read_applied,
)

from integrations.gateway import applied


def dump():
    return {
        "workloads": [],
        "services": [],
        "binds": [],
        "routes": {},
        "policies": [],
        "models": [],
        "version": {},
        "config": {},
        "backends": [
            {
                "backend": {
                    "ai": {
                        "target": {
                            "providers": [
                                {
                                    "active": {
                                        "model": {
                                            "endpoint": {
                                                "hostOverride": "provider.invalid:443"
                                            },
                                            "capacity": 1,
                                            "info": {
                                                "health": 1,
                                                "requestLatency": 0,
                                                "pendingRequests": 0,
                                                "totalRequests": 0,
                                                "consecutiveFailures": 0,
                                                "timesEjected": 0,
                                                "evictedUntil": None,
                                            },
                                        }
                                    },
                                    "rejected": {},
                                }
                            ]
                        }
                    }
                }
            }
        ],
    }


def test_only_evidenced_request_measurements_are_excluded():
    before = dump()
    after = deepcopy(before)
    info = after["backends"][0]["backend"]["ai"]["target"]["providers"][0]["active"][
        "model"
    ]["info"]
    info.update(
        requestLatency=0.03,
        pendingRequests=2,
        totalRequests=123,
        health=0.7,
        consecutiveFailures=1,
    )
    assert applied_fingerprint(before) == applied_fingerprint(after)
    assert before == dump()


@pytest.mark.parametrize(
    "field",
    [
        "endpoint",
        "capacity",
        "timesEjected",
        "evictedUntil",
        "unknown",
        "policy",
        "created",
        "membership",
        "health-policy",
    ],
)
def test_definition_eviction_policy_and_unknown_fields_remain_bound(field):
    before = dump()
    after = deepcopy(before)
    endpoint = after["backends"][0]["backend"]["ai"]["target"]["providers"][0][
        "active"
    ]["model"]
    if field == "endpoint":
        endpoint["endpoint"]["hostOverride"] = "changed.invalid:443"
    elif field == "capacity":
        endpoint["capacity"] = 2
    elif field in ("timesEjected", "evictedUntil"):
        endpoint["info"][field] = 1
    elif field == "unknown":
        endpoint["info"]["unknown"] = True
    elif field == "membership":
        group = after["backends"][0]["backend"]["ai"]["target"]["providers"][0]
        group["rejected"]["model"] = group["active"].pop("model")
    elif field == "health-policy":
        after["policies"].append({"health": {"eviction": {"consecutiveFailures": 2}}})
    else:
        after[field] = {"changed": True}
    if field in ("policy", "created"):
        # Put these inside an existing resource; unknown top-level schema denies.
        after["backends"][0][field] = after.pop(field)
    assert applied_fingerprint(before) != applied_fingerprint(after)


@pytest.mark.parametrize("location", ["policy", "config", "endpoint", "unknown"])
def test_same_named_measurements_outside_exact_info_path_are_not_removed(location):
    before = dump()
    after = deepcopy(before)
    values = {
        "requestLatency": 1,
        "pendingRequests": 2,
        "totalRequests": 3,
        "health": 0.7,
        "consecutiveFailures": 1,
    }
    if location == "policy":
        after["policies"].append(values)
    elif location == "config":
        after["config"].update(values)
    elif location == "endpoint":
        after["backends"][0]["backend"]["ai"]["target"]["providers"][0]["active"][
            "model"
        ]["endpoint"].update(values)
    else:
        after["backends"][0]["unknown"] = values
    assert applied_fingerprint(before) != applied_fingerprint(after)


@pytest.mark.parametrize(
    "field,value",
    [
        ("health", value)
        for value in (None, True, "0.7", {}, -0.1, 1.1, float("nan"), float("inf"))
    ]
    + [
        ("consecutiveFailures", value)
        for value in (None, True, 1.0, "1", {}, -1, 2**64)
    ],
)
def test_malformed_health_measurements_fail_closed(field, value):
    changed = dump()
    info = changed["backends"][0]["backend"]["ai"]["target"]["providers"][0]["active"][
        "model"
    ]["info"]
    info[field] = value
    with pytest.raises(AppliedStateUnavailable):
        applied_fingerprint(changed)


@pytest.mark.parametrize("field", ["health", "consecutiveFailures"])
def test_missing_health_measurement_is_not_silently_ignored(field):
    changed = dump()
    del changed["backends"][0]["backend"]["ai"]["target"]["providers"][0]["active"][
        "model"
    ]["info"][field]
    with pytest.raises(AppliedStateUnavailable):
        applied_fingerprint(changed)


@pytest.mark.parametrize("health,failures", [(0, 0), (1, 2**64 - 1), (0.3, 5)])
def test_native_health_measurement_bounds_are_supported(health, failures):
    changed = dump()
    changed["backends"][0]["backend"]["ai"]["target"]["providers"][0]["active"][
        "model"
    ]["info"].update(health=health, consecutiveFailures=failures)
    assert applied_fingerprint(changed) == applied_fingerprint(dump())


@pytest.mark.parametrize(
    "value", [None, {}, {"backends": []}, dict(dump(), unexpected=True)]
)
def test_incomplete_or_changed_dump_schema_denies(value):
    with pytest.raises(AppliedStateUnavailable):
        applied_fingerprint(value)


@pytest.fixture
def native(tmp_path):
    state = SimpleNamespace(
        status=200,
        content_type="application/json",
        body=json.dumps(dump()).encode(),
        calls=[],
    )
    key = secrets.token_urlsafe(32)
    key_file = tmp_path / "runtime-key"
    key_file.write_text(key)
    state.key, state.key_file = key, key_file

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            state.calls.append(
                {
                    "path": self.path,
                    "key_matches": self.headers.get("Authorization")
                    == "Bearer " + state.key,
                }
            )
            self.send_response(state.status)
            self.send_header("Content-Type", state.content_type)
            self.send_header("Content-Length", str(len(state.body)))
            if state.status == 302:
                self.send_header("Location", "/redirect-target")
            self.end_headers()
            try:
                self.wfile.write(state.body)
            except (ConnectionResetError, BrokenPipeError):
                pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    state.gateway = SimpleNamespace(
        base_url="http://127.0.0.1:" + str(server.server_port),
        runtime_key_file=str(key_file),
    )
    try:
        yield state
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_private_read_uses_only_current_server_credential(native):
    assert read_applied(native.gateway) == dump()
    assert native.calls == [{"path": "/internal/keeplane/applied", "key_matches": True}]
    replacement = native.key_file.with_suffix(".new")
    native.key = secrets.token_urlsafe(32)
    replacement.write_text(native.key)
    replacement.replace(native.key_file)
    assert read_applied(native.gateway) == dump()
    assert len(native.calls) == 2 and native.calls[-1]["key_matches"]


def test_fault_injected_http_error_response_is_explicitly_closed(native, monkeypatch):
    body = io.BytesIO(b"untrusted error body")

    def fail(*args, **kwargs):
        raise HTTPError(native.gateway.base_url, 403, "refused", {}, body)

    monkeypatch.setattr(
        applied, "build_opener", lambda *args: SimpleNamespace(open=fail)
    )
    with pytest.raises(AppliedStateUnavailable):
        read_applied(native.gateway)
    assert body.closed
    assert not native.calls


@pytest.mark.parametrize(
    "failure",
    ["redirect", "denied", "outage", "content-type", "oversized", "json", "duplicate"],
)
def test_unavailable_or_malformed_response_denies_without_redirect_or_retry(
    native, failure
):
    if failure in ("redirect", "denied", "outage"):
        native.status = {"redirect": 302, "denied": 403, "outage": 503}[failure]
    elif failure == "content-type":
        native.content_type = "text/plain"
    else:
        native.body = {
            "oversized": b"x" * (MAX_APPLIED_BYTES + 1),
            "json": b"[" * 1000,
            "duplicate": b'{"config":{},"config":{}}',
        }[failure]
    with pytest.raises(AppliedStateUnavailable) as error:
        read_applied(native.gateway)
    assert str(error.value) == "Applied runtime configuration is unavailable"
    assert (
        len(native.calls) == 1
        and native.calls[0]["path"] == "/internal/keeplane/applied"
    )


@pytest.mark.parametrize(
    "failure",
    ["relative", "missing", "malformed", "oversized", "userinfo", "path", "control"],
)
def test_bad_configuration_refuses_before_contact(native, failure):
    if failure == "relative":
        native.gateway.runtime_key_file = "runtime-key"
    elif failure == "missing":
        native.key_file.unlink()
    elif failure in ("malformed", "oversized"):
        native.key_file.write_text("bad key" if failure == "malformed" else "a" * 259)
    else:
        native.gateway.base_url = {
            "userinfo": "http://user:secret@127.0.0.1",
            "path": native.gateway.base_url + "/prefix",
            "control": native.gateway.base_url + "\n",
        }[failure]
    with pytest.raises(AppliedStateUnavailable):
        read_applied(native.gateway)
    assert not native.calls
