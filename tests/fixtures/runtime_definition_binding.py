"""Controlled publication generations, not native definition self-attestation."""

import json
import os
import time
from pathlib import Path

from common.api import MODEL_GATEWAY
from common.stores import stores
from integrations.gateway.adapter import AgentgatewayModelAdapter
from model_registry.fingerprints import fingerprint
from runtime_actor_keys import PATH as KEY_PATH
from runtime_actor_keys import actors, change_key

HEADER = "x-keeplane-definition-generation"
ENTRY = "/fixture/definition-entry"
SELECTED = "/fixture/definition-selected"


def generation(label):
    return Path("/trial/generation-" + label).read_text()


def rule(label):
    # Native model authorization also filters discovery; this GET never dispatches.
    return (
        '(request.method == "GET" && request.path == "/v1/models") || '
        f'request.headers["{HEADER}"] == "{generation(label)}"'
    )


def configure(definitions):
    for definition in definitions:
        if definition["id"] == "private":
            definition["params"]["model"] = "mock-generation-a"
            definition["authorization"] = {"rules": [{"require": rule("a")}]}
        definition["requestHeaders"]["remove"].append(HEADER)


def binding(state):
    return json.loads((state / "definition-binding").read_text())


def wait_active(port, label, model):
    key = os.environ["GATEWAY_ADMIN_KEY_FILE"]
    admin = AgentgatewayModelAdapter(f"http://127.0.0.1:{port}", key, key)
    deadline = time.monotonic() + 10
    while True:
        status, body = admin.request("/config_dump", timeout=1)
        active = body.get("backends", []) if isinstance(body, dict) else []
        # Keep the inline rule and provider parameters on the same active backend.
        matching = any(
            all(
                value in json.dumps(backend)
                for value in ("llm:model:private", generation(label), model)
            )
            for backend in active
        )
        if status == 200 and matching:
            return
        if time.monotonic() >= deadline:
            raise RuntimeError("Disposable native generation did not become active")
        time.sleep(0.1)


def publish(state, definition, *, reused=False):
    selected_generation = generation("a" if reused else "b")
    used = json.loads((state / "used-generations").read_text())
    if selected_generation in used and not reused:
        raise ValueError("A publication generation cannot be reused")
    status, _ = MODEL_GATEWAY.request(
        "/api/config/resources/llm.model/private", {"value": definition}, method="PUT"
    )
    assert status == 200
    status, body = MODEL_GATEWAY.resources()
    assert status == 200
    digest = fingerprint("private", body["resources"])
    stores()[2].approve("private", ["Confidential"], digest, key_choice="none")
    change_key(state, "a")
    rows = actors(state)
    rows["a"]["gateway_fingerprint"] = digest
    (state / "actors").write_text(json.dumps(rows))
    (state / "definition-binding").write_text(
        json.dumps(
            {
                "fingerprint": digest,
                "generation": selected_generation,
            }
        )
    )
    (state / "used-generations").write_text(json.dumps(used + [selected_generation]))
    wait_active(15000, "a" if reused else "b", "mock-generation-b")


def seed(state, definitions):
    (state / "used-generations").write_text(json.dumps([generation("a")]))
    key = os.environ["GATEWAY_ADMIN_KEY_FILE"]
    stale = AgentgatewayModelAdapter("http://127.0.0.1:4001", key, key)
    deadline = time.monotonic() + 10
    while stale.request("/v1/models", timeout=1)[0] != 200:
        if time.monotonic() >= deadline:
            raise RuntimeError("Stale disposable copy did not start")
        time.sleep(0.1)
    old = json.loads(
        json.dumps(next(row for row in definitions if row["id"] == "private"))
    )
    old["params"]["model"] = "mock-generation-a"
    old["authorization"]["rules"][0]["require"] = rule("a")
    status, _ = stale.request(
        "/api/config/resources/llm.model", {"resources": [{"value": old}]}, method="PUT"
    )
    assert status == 200
    wait_active(15010, "a", "mock-generation-a")
    current = json.loads(
        json.dumps(next(row for row in definitions if row["id"] == "private"))
    )
    current["params"]["model"] = "mock-generation-b"
    current["authorization"]["rules"][0]["require"] = rule("b")
    publish(state, current)


def command(state, action):
    if action == "binding_versions":
        key = os.environ["GATEWAY_ADMIN_KEY_FILE"]
        stale = AgentgatewayModelAdapter("http://127.0.0.1:4001", key, key)
        current_status, current = MODEL_GATEWAY.resources()
        stale_status, previous = stale.resources()
        assert current_status == stale_status == 200
        latest = next(row for row in current["resources"] if row["id"] == "private")
        old = next(row for row in previous["resources"] if row["id"] == "private")
        return {
            "same_model_id": latest["id"] == old["id"],
            "same_endpoint": latest["value"]["params"]["baseUrl"]
            == old["value"]["params"]["baseUrl"],
            "current_revision": latest["revision"],
            "stale_revision": old["revision"],
            "different_parameters": latest["value"]["params"] != old["value"]["params"],
        }
    if action == "binding_summary":
        return {
            "key_callbacks": (state / "key-callbacks").read_text().splitlines()
            if (state / "key-callbacks").exists()
            else [],
            "checks": [
                json.loads(line)
                for line in (state / "binding-checks").read_text().splitlines()
            ]
            if (state / "binding-checks").exists()
            else [],
        }
    if action == "binding_reset":
        (state / "key-callbacks").unlink(missing_ok=True)
        (state / "binding-checks").unlink(missing_ok=True)
        return
    status, body = MODEL_GATEWAY.resources()
    assert status == 200
    current = next(row["value"] for row in body["resources"] if row["id"] == "private")
    if action == "binding_outside_edit":
        current["params"]["model"] = "mock-outside-edit"
        status, _ = MODEL_GATEWAY.request(
            "/api/config/resources/llm.model/private", {"value": current}, method="PUT"
        )
        assert status == 200
    elif action == "binding_reject_reuse":
        try:
            publish(state, current)
        except ValueError:
            return True
        return False
    elif action == "binding_reuse_control":
        # Intentionally unsafe operator control: do not copy this into a publisher.
        current["authorization"]["rules"][0]["require"] = rule("a")
        publish(state, current, reused=True)


def wrap(application, state):
    def authorized(environ, start_response):
        stage = environ["PATH_INFO"]
        if stage not in (ENTRY, SELECTED):
            return application(environ, start_response)
        current = binding(state)
        status, body = MODEL_GATEWAY.resources()
        list_status, listing = MODEL_GATEWAY.models()
        visible = list_status == 200 and any(
            row.get("id") == "private" for row in listing.get("data", [])
        )
        approval = stores()[2].get("private")
        valid = (
            status == 200
            and approval
            and approval["gateway_fingerprint"] == current["fingerprint"]
            and fingerprint("private", body["resources"]) == current["fingerprint"]
            and actors(state)["a"]["gateway_fingerprint"] == current["fingerprint"]
        )
        if stage == SELECTED:
            with (state / "key-callbacks").open("a") as log:
                log.write("selected\n")
            valid = (
                valid
                and environ.get("HTTP_X_KEEPLANE_DEFINITION_GENERATION")
                == current["generation"]
            )

        def observe(status, headers, exc_info=None):
            with (state / "binding-checks").open("a") as log:
                log.write(
                    json.dumps(
                        {
                            "stage": "selected" if stage == SELECTED else "entry",
                            "status": int(status.split()[0]),
                            "binding_current": bool(valid),
                            "catalog_visible": visible,
                            "generation_matches": environ.get(
                                "HTTP_X_KEEPLANE_DEFINITION_GENERATION"
                            )
                            == current["generation"],
                            "generation_added": any(
                                name.lower() == HEADER for name, _ in headers
                            ),
                        }
                    )
                    + "\n"
                )
            return start_response(status, headers, exc_info)

        if not valid:
            observe("403 Forbidden", [("Content-Length", "0")])
            return [b""]
        environ["PATH_INFO"] = (
            KEY_PATH if stage == SELECTED else "/internal/runtime/authorize"
        )
        if stage == SELECTED:
            return application(environ, observe)

        def include_generation(status, headers, exc_info=None):
            if status.startswith("200 "):
                headers.append((HEADER, current["generation"]))
            return observe(status, headers, exc_info)

        return application(environ, include_generation)

    return authorized
