"""Fixed two-candidate publication map; disposable and never a production issuer."""

import io
import json
import time
import uuid

from common.api import MODEL_GATEWAY
from common.stores import stores
from model_registry.fingerprints import fingerprint
from model_registry.policy import DjangoModelPolicy
from runtime_actor_keys import actors, key_file
from runtime_definition_binding import (
    ENTRY,
    HEADER,
    SELECTED,
    binding,
    generation,
    wait_active,
)
from runtime_definition_binding import seed as seed_private

MODELS = ("private", "public")
ALIAS_HEADER = "x-fixture-requested-alias"


def claim_generation(state, nonce):
    used = json.loads((state / "used-generations").read_text())
    if nonce in used:
        raise ValueError("A publication generation cannot be reused")
    (state / "used-generations").write_text(json.dumps(used + [nonce]))


def public_rule(nonce):
    return {
        "rules": [
            {
                "require": '(request.method == "GET" && request.path == "/v1/models") || '
                f'(size(request.headers["{HEADER}"]) <= 256 && '
                f'json(request.headers["{HEADER}"])["public"] == "{nonce}")'
            }
        ]
    }


def configure(definitions, state):
    from runtime_definition_binding import configure as configure_private

    configure_private(definitions)
    nonce = uuid.uuid4().hex
    (state / "old-public-generation").write_text(nonce)
    for model in definitions:
        model["requestHeaders"]["remove"].append(ALIAS_HEADER)
        if model["id"] == "public":
            model["authorization"] = public_rule(nonce)


def stale_adapter():
    import os

    from integrations.gateway.adapter import AgentgatewayModelAdapter

    key = os.environ["GATEWAY_ADMIN_KEY_FILE"]
    return AgentgatewayModelAdapter("http://127.0.0.1:4001", key, key)


def write_model(gateway, definition, *, create=False):
    path, body = "/api/config/resources/llm.model", {"value": definition}
    if create:
        body = {"resources": [body]}
    else:
        path += "/" + definition["id"]
    assert gateway.request(path, body, method="PUT")[0] == 200


def wait_alias(port, nonce, model):
    import os

    from integrations.gateway.adapter import AgentgatewayModelAdapter

    key = os.environ["GATEWAY_ADMIN_KEY_FILE"]
    admin = AgentgatewayModelAdapter(f"http://127.0.0.1:{port}", key, key)
    deadline = time.monotonic() + 10
    while True:
        status, body = admin.request("/config_dump", timeout=1)
        if status == 200 and any(
            all(
                part in json.dumps(row)
                for part in (
                    "llm:virtual-model:fallback:0",
                    generation("b"),
                    "mock-generation-b",
                    nonce,
                    model,
                )
            )
            for row in body.get("backends", [])
        ):
            return
        if time.monotonic() >= deadline:
            raise RuntimeError("Disposable fallback generation did not become active")
        time.sleep(0.1)


def seed(state, definitions):
    seed_private(state, definitions)
    claim_generation(state, (state / "old-public-generation").read_text())
    status, current = MODEL_GATEWAY.resources()
    assert status == 200
    private = next(
        row["value"] for row in current["resources"] if row["id"] == "private"
    )
    stale = stale_adapter()
    write_model(stale, private)
    old_public = next(row for row in definitions if row["id"] == "public")
    write_model(stale, old_public, create=True)
    status, virtual = MODEL_GATEWAY.request("/api/config/resources/llm.virtualModel")
    assert status == 200
    assert (
        stale.request(
            "/api/config/resources/llm.virtualModel",
            {"resources": [{"value": row["value"]} for row in virtual["resources"]]},
            method="PUT",
        )[0]
        == 200
    )
    nonce = uuid.uuid4().hex
    claim_generation(state, nonce)
    new_public = json.loads(json.dumps(old_public))
    new_public["params"]["model"] = "mock-public-current"
    new_public["authorization"] = public_rule(nonce)
    write_model(MODEL_GATEWAY, new_public)
    status, current = MODEL_GATEWAY.resources()
    assert status == 200
    digest = fingerprint("public", current["resources"])
    stores()[2].approve("public", ["Confidential"], digest, key_choice="none")
    data = {
        "private": binding(state),
        "public": {"generation": nonce, "fingerprint": digest},
    }
    (state / "fallback-bindings").write_text(json.dumps(data))
    rows = actors(state)
    rows["a"]["model_fingerprints"] = {
        name: row["fingerprint"] for name, row in data.items()
    }
    (state / "actors").write_text(json.dumps(rows))
    wait_active(15010, "b", "mock-generation-b")
    wait_alias(15000, nonce, "mock-public-current")
    wait_alias(15010, (state / "old-public-generation").read_text(), "mock-public")


def current_bindings(state):
    data = json.loads((state / "fallback-bindings").read_text())
    status, registry = MODEL_GATEWAY.resources()
    if status != 200:
        return {}
    actor = actors(state)["a"]
    return {
        name: row
        for name, row in data.items()
        if (
            fingerprint(name, registry["resources"]) == row["fingerprint"]
            and (stores()[2].get(name) or {}).get("gateway_fingerprint")
            == row["fingerprint"]
            and actor["model_fingerprints"].get(name) == row["fingerprint"]
            and key_file(state, actor).is_file()
        )
    }


def parse_map(value):
    if not value or len(value.encode()) > 256:
        raise ValueError("Missing or oversized fixture marker map")
    data = json.loads(value)
    if (
        not isinstance(data, dict)
        or not data
        or set(data) - set(MODELS)
        or any(
            not isinstance(nonce, str)
            or len(nonce) != 32
            or any(char not in "0123456789abcdef" for char in nonce)
            for nonce in data.values()
        )
    ):
        raise ValueError("Malformed fixture marker map")
    return data


def wrap(application, state):
    def authorize(environ, start_response):
        stage = environ["PATH_INFO"]
        if stage not in (ENTRY, SELECTED):
            return application(environ, start_response)
        raw = environ["wsgi.input"].read(int(environ.get("CONTENT_LENGTH") or 0))
        environ["wsgi.input"] = io.BytesIO(raw)
        model = json.loads(raw)["model_id"]
        data = current_bindings(state)
        response = []

        def capture(status, headers, exc_info=None):
            response[:] = [status, headers]

        def finish(status, headers, body, marker_models=()):
            with (state / "binding-checks").open("a") as output:
                output.write(
                    json.dumps(
                        {
                            "stage": "entry" if stage == ENTRY else "selected",
                            "model": model,
                            "status": int(status.split()[0]),
                            "marker_models": list(marker_models),
                        }
                    )
                    + "\n"
                )
            start_response(status, headers)
            return [body]

        if (
            stage == ENTRY
            and environ.get("HTTP_X_FIXTURE_REQUESTED_ALIAS") != "fallback"
        ):
            return finish("403 Forbidden", [("Content-Length", "0")], b"")
        if stage == SELECTED:
            with (state / "key-callbacks").open("a") as output:
                output.write(model + "\n")
            try:
                supplied = parse_map(
                    environ.get("HTTP_X_KEEPLANE_DEFINITION_GENERATION", "")
                )
            except ValueError:
                return finish("403 Forbidden", [("Content-Length", "0")], b"")
            if model not in data or supplied.get(model) != data[model]["generation"]:
                return finish("403 Forbidden", [("Content-Length", "0")], b"")
        environ["PATH_INFO"] = "/internal/runtime/authorize"
        result = application(environ, capture)
        try:
            body = b"".join(result)
        finally:
            if hasattr(result, "close"):
                result.close()
        status, headers = response
        if not status.startswith("200 "):
            return finish(status, headers, body)
        canonical = json.loads(body)
        actor = actors(state)["a"]
        eligible = DjangoModelPolicy(MODEL_GATEWAY).eligible_model_ids(
            canonical["project_id"]
        )
        data = {
            name: row
            for name, row in current_bindings(state).items()
            if name in eligible
        }
        if (
            canonical["actor_id"] != actor["actor_id"]
            or canonical["model_id"] != model
            or model not in data
            or (stage == SELECTED and supplied.get(model) != data[model]["generation"])
        ):
            return finish("403 Forbidden", [("Content-Length", "0")], b"")
        if stage == ENTRY:
            marker = json.dumps(
                {name: row["generation"] for name, row in data.items()},
                separators=(",", ":"),
            )
            parse_map(marker)
            fault = (
                (state / "map-fault").read_text()
                if (state / "map-fault").exists()
                else ""
            )
            # Deliberate authorizer faults still overwrite the caller's header.
            marker = {
                "missing": "",
                "malformed": "{",
                "oversized": json.dumps({**parse_map(marker), "padding": "x" * 256}),
            }.get(fault, marker)
            headers.append((HEADER, marker))
        else:
            try:
                key = key_file(state, actor).read_text()
            except OSError:
                key = ""
            if not key:
                return finish("403 Forbidden", [("Content-Length", "0")], b"")
            headers.append(("Authorization", "Bearer " + key))
        return finish(status, headers, body, sorted(data))

    return authorize


def command(state, action, argument):
    if action == "fallback_binding_map":
        return json.dumps(
            {
                name: row["generation"]
                for name, row in json.loads(
                    (state / "fallback-bindings").read_text()
                ).items()
            }
        )
    if action == "fallback_binding_reject_reuse":
        row = json.loads((state / "fallback-bindings").read_text())["public"]
        try:
            claim_generation(state, row["generation"])
        except ValueError:
            return True
        return False
    if action == "fallback_binding_fault":
        assert argument in ("missing", "malformed", "oversized", "")
        (state / "map-fault").write_text(argument)
    elif action == "fallback_binding_outside":
        status, registry = MODEL_GATEWAY.resources()
        assert status == 200
        public = next(
            row["value"] for row in registry["resources"] if row["id"] == "public"
        )
        public["params"]["model"] = "mock-public-outside"
        write_model(MODEL_GATEWAY, public)
        nonce = json.loads((state / "fallback-bindings").read_text())["public"][
            "generation"
        ]
        wait_alias(15000, nonce, "mock-public-outside")
    elif action == "fallback_binding_restore":
        row = json.loads((state / "fallback-bindings").read_text())["public"]
        stores()[2].approve(
            "public", ["Confidential"], row["fingerprint"], key_choice="none"
        )
    elif action == "fallback_binding_versions":
        status, current = MODEL_GATEWAY.resources()
        old_status, old = stale_adapter().resources()
        assert status == old_status == 200
        latest = next(row for row in current["resources"] if row["id"] == "public")
        previous = next(row for row in old["resources"] if row["id"] == "public")
        return {
            "current_revision": latest["revision"],
            "stale_revision": previous["revision"],
            "same_endpoint": latest["value"]["params"]["baseUrl"]
            == previous["value"]["params"]["baseUrl"],
            "private_current_on_both": fingerprint("private", current["resources"])
            == fingerprint("private", old["resources"]),
        }
