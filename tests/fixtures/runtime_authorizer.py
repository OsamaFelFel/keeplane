"""Disposable real-Django authorizer and mock provider; never use for deployment."""

import hashlib
import io
import json
import os
import signal
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from wsgiref.simple_server import WSGIRequestHandler, make_server

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django

django.setup()

from common.api import MODEL_GATEWAY
from common.stores import stores
from data_classes.models import ProjectClass
from django.core.management import call_command
from django.core.wsgi import get_wsgi_application
from django.db import connection
from model_registry.fingerprints import fingerprint
from projects.services import DjangoProjectStore

STATE = Path("/state")


def append(name, value):
    with (STATE / name).open("a") as output:
        output.write(json.dumps(value) + "\n")


def rows(name):
    path = STATE / name
    return (
        [json.loads(line) for line in path.read_text().splitlines()]
        if path.exists()
        else []
    )


class Silent(WSGIRequestHandler):
    def log_message(self, *args):
        pass


OUTAGE_LOCK = threading.Lock()
CONTEXT_TOO_BIG = {
    "error": {
        "message": "This model's maximum context length is 8 tokens.",
        "type": "invalid_request_error",
        "code": "context_length_exceeded",
    }
}


def outage_step(handler, body):
    """Play the next scripted provider failure; return True if it answered.

    Steps are an HTTP status such as "503", "slow" (answer after the gateway's
    per-attempt timeout), "context" (a context-length refusal), "mid" (drop a
    stream after its first event) or "ok" (answer normally).
    """
    script = STATE / "outage-script"
    with OUTAGE_LOCK:
        steps = json.loads(script.read_text()) if script.exists() else []
        if not steps:
            return False
        step = steps.pop(0)
        script.write_text(json.dumps(steps))
    append("outage_steps", step)
    if step == "ok":
        return False
    if step == "slow":
        time.sleep(6)
        return False
    if step == "mid":
        from runtime_protocol import send_failed_stream

        send_failed_stream(handler, body, "mid")
        return True
    status, data = (400, CONTEXT_TOO_BIG) if step == "context" else (int(step), None)
    data = json.dumps(
        data or {"error": {"message": "Synthetic outage", "type": "server_error"}}
    ).encode()
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)
    return True


class Model(BaseHTTPRequestHandler):
    requires_key = False
    fail_private = False
    protocol = False
    actor_keys = False
    bound_definition = False
    fail_private_model = "mock-private"

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        append("calls", body["model"])
        authorization = self.headers.get("Authorization", "")
        expected = (
            Path("/trial/provider-expected").read_text().strip()
            if self.requires_key
            else ""
        )
        key_matches = self.requires_key and authorization == "Bearer " + expected
        actor_developer_forwarded = False
        if self.actor_keys:
            from runtime_actor_keys import STRIP_HEADERS, provider_identity

            actor, actor_developer_forwarded = provider_identity(STATE, authorization)
            key_matches = actor is not None
            append("provider_actor", actor)
            append(
                "forged_headers",
                any(name in self.headers for name in STRIP_HEADERS)
                or (
                    os.environ.get("FIXTURE_DEFINITION_FALLBACK") == "1"
                    and "x-fixture-requested-alias" in self.headers
                ),
            )
        if self.bound_definition:
            append(
                "generation_forwarded",
                "x-keeplane-definition-generation" in self.headers,
            )
        append("provider_key_used", key_matches)
        token = json.loads((STATE / "credential").read_text())["token"]
        append(
            "developer_key_forwarded",
            token in authorization or actor_developer_forwarded,
        )
        append(
            "credential_headers",
            {
                name: name in self.headers
                for name in (
                    "Authorization",
                    "X-Keeplane-Gateway-Credential",
                    "X-Keeplane-Project-ID",
                )
            },
        )
        if self.requires_key and not key_matches:
            self.send_response(401)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if outage_step(self, body):
            return
        if self.fail_private and body["model"] == self.fail_private_model:
            self.send_response(503)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if self.protocol:
            from runtime_protocol import (
                received_settings,
                send_failed_stream,
                send_protocol_response,
            )

            append("settings", received_settings(body))
            failure = STATE / "protocol-failure"
            if failure.exists():
                send_failed_stream(self, body, failure.read_text())
                return
            append("tool_result_seen", send_protocol_response(self, body))
            return
        data = json.dumps(
            {
                "id": "fixture",
                "object": "chat.completion",
                "model": body["model"],
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "OK"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 1,
                    "completion_tokens": 1,
                    "total_tokens": 2,
                },
            }
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


def serve():
    call_command("migrate", verbosity=0)
    _, identity, catalog, classes = stores()
    seed = Path(os.environ.get("FIXTURE_SESSION_FILE", "/trial/no-seed"))
    seeded = seed.is_file()
    if seeded:
        credential = json.loads(seed.read_text())
        token, project = credential["token"], credential["project"]
    else:
        password = "isolated-runtime-developer-password"
        actor = identity.create_user(
            {"username": "runtime-fixture", "password": password, "role": "developer"}
        )
        token, project = identity.login(actor["username"], password), str(uuid.uuid4())
        DjangoProjectStore().register_use(actor["id"], project, "Native authorization")
    if not seeded:
        classes.set_enabled(True)
        ProjectClass.objects.create(project_id=project, data_class_id="confidential")
    shared = os.environ.get("FIXTURE_SHARED_PROVIDER_KEY") == "1"
    fallback = os.environ.get("FIXTURE_NATIVE_FALLBACK") == "1"
    actor_keys = os.environ.get("FIXTURE_NATIVE_ACTOR_KEYS") == "1"
    Model.fail_private = fallback
    Model.protocol = os.environ.get("FIXTURE_NATIVE_PROTOCOL") == "1"
    Model.actor_keys = actor_keys
    if shared:
        Model.requires_key = True
    definitions = [
        {
            "id": name,
            "name": name,
            "provider": {"custom": {"formats": [{"type": "completions"}]}},
            "params": {"model": "mock-" + name, "baseUrl": "http://127.0.0.1:18080/v1"},
            "requestHeaders": {
                "remove": [
                    "authorization",
                    "x-keeplane-gateway-credential",
                    "x-keeplane-project-id",
                ]
            },
        }
        for name in ("private", "public", "outside")
    ]
    if fallback:
        for definition in definitions:
            definition["health"] = {
                "eviction": {"duration": "120s", "consecutiveFailures": 1}
            }
    if shared:
        for definition in definitions:
            definition["auth"] = {
                "key": {
                    "value": {
                        "file": str(
                            Path("/trial") / os.environ["FIXTURE_PROVIDER_KEY_NAME"]
                        )
                    }
                }
            }
            if fallback and definition["id"] == "public":
                definition["auth"]["key"]["value"] = {
                    "file": str(
                        Path("/trial") / os.environ["FIXTURE_PROVIDER_NEXT_KEY_NAME"]
                    )
                }
            definition["requestHeaders"]["remove"].remove("authorization")
    if actor_keys:
        from runtime_actor_keys import STRIP_HEADERS, seed

        seed(STATE, identity, token, project)
        Model.requires_key = True
        for definition in definitions:
            definition["requestHeaders"]["remove"].remove("authorization")
            definition["requestHeaders"]["remove"].extend(STRIP_HEADERS)
    bound_definition = os.environ.get("FIXTURE_DEFINITION_BINDING") == "1"
    Model.bound_definition = bound_definition
    if bound_definition:
        import importlib

        definition_fallback = os.environ.get("FIXTURE_DEFINITION_FALLBACK") == "1"
        binding_module = importlib.import_module(
            "runtime_fallback_binding"
            if definition_fallback
            else "runtime_definition_binding"
        )
        if definition_fallback:
            Model.fail_private_model = "mock-generation-b"
            binding_module.configure(definitions, STATE)
            for definition in definitions:
                definition["health"]["eviction"]["duration"] = "600s"
        else:
            binding_module.configure(definitions)
    reuse = False
    if os.environ.get("FIXTURE_REUSE_NATIVE_DEFINITIONS") == "1":
        status, current = MODEL_GATEWAY.resources()
        reuse = status == 200 and all(
            any(row.get("value") == model for row in current["resources"])
            for model in definitions
        )
    if not reuse:
        status, _ = MODEL_GATEWAY.request(
            "/api/config/resources/llm.model",
            {"resources": [{"value": model} for model in definitions]},
            method="PUT",
        )
        if status != 200:
            raise RuntimeError("Disposable native model registration failed")
    status, resource_body = MODEL_GATEWAY.resources()
    if status != 200:
        raise RuntimeError("Disposable native registry did not start")
    if not reuse:
        for name, approved in (("private", ["Confidential"]), ("public", ["Public"])):
            catalog.approve(
                name,
                approved,
                fingerprint(name, resource_body["resources"]),
                key_choice="shared" if shared else "none",
            )
    if fallback:
        status, _ = MODEL_GATEWAY.request(
            "/api/config/resources/llm.virtualModel",
            {
                "resources": [
                    {
                        "value": {
                            "name": "fallback",
                            "routing": {
                                "failover": {
                                    "targets": [
                                        {"model": "private", "priority": 0},
                                        {"model": "public", "priority": 1},
                                    ]
                                }
                            },
                        }
                    }
                ]
            },
            method="PUT",
        )
        assert status == 200
    credential = STATE / "credential"
    credential.write_text(json.dumps({"token": token, "project": project}))
    credential.chmod(0o600)
    if bound_definition:
        binding_module.seed(STATE, definitions)
    application = get_wsgi_application()
    if actor_keys:
        from runtime_actor_keys import wrap

        application = wrap(application, STATE)
    if bound_definition:
        application = binding_module.wrap(application, STATE)

    def recorded(environ, start_response):
        raw = environ["wsgi.input"].read(int(environ.get("CONTENT_LENGTH") or 0))
        environ["wsgi.input"] = io.BytesIO(raw)
        metadata = json.loads(raw)

        # Store only the metadata contract, never headers or prompt text.
        def record_response(status, headers, exc_info=None):
            append(
                "decisions",
                {
                    "keys": sorted(metadata),
                    "project_id": metadata.get("project_id"),
                    "model_id": metadata.get("model_id"),
                    "status": int(status.split(" ", 1)[0]),
                },
            )
            return start_response(status, headers, exc_info)

        return application(environ, record_response)

    mock = ThreadingHTTPServer(("127.0.0.1", 18080), Model)
    threading.Thread(target=mock.serve_forever, daemon=True).start()
    authorizer = make_server("127.0.0.1", 8090, recorded, handler_class=Silent)
    threading.Thread(target=authorizer.serve_forever, daemon=True).start()

    def stop_authorizer(*args):
        authorizer.shutdown()
        authorizer.server_close()

    signal.signal(signal.SIGUSR1, stop_authorizer)
    (STATE / "ready").touch()
    while True:
        time.sleep(1)


def command(action, arguments):
    credential = json.loads((STATE / "credential").read_text())
    if action.startswith("fallback_binding_"):
        from runtime_fallback_binding import command as fallback_binding_command

        return fallback_binding_command(STATE, action, arguments)
    if action.startswith("binding_"):
        from runtime_definition_binding import command as binding_command

        return binding_command(STATE, action)
    if action == "withdraw":
        stores()[2].remove("private")
    elif action == "restore_approval":
        status, body = MODEL_GATEWAY.resources()
        assert status == 200
        stores()[2].approve(
            "private",
            ["Confidential"],
            fingerprint("private", body["resources"]),
            key_choice="shared"
            if os.environ.get("FIXTURE_SHARED_PROVIDER_KEY") == "1"
            else "none",
        )
    elif action == "set_class":
        assert arguments in ("public", "confidential")
        ProjectClass.objects.filter(project_id=credential["project"]).update(
            data_class_id=arguments
        )
    elif action == "database_state":
        assert connection.vendor == "postgresql"
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_is_in_recovery()")
            return {"vendor": connection.vendor, "standby": cursor.fetchone()[0]}
    elif action == "set_classes":
        assert arguments in ("enabled", "disabled")
        return stores()[3].set_enabled(arguments == "enabled")
    elif action == "classes_enabled":
        return stores()[3].enabled()
    elif action == "allow_public":
        status, body = MODEL_GATEWAY.resources()
        assert status == 200
        stores()[2].approve(
            "public",
            ["Confidential"],
            fingerprint("public", body["resources"]),
            key_choice="shared",
        )
    elif action == "withdraw_public":
        stores()[2].remove("public")
    elif action == "active_fallback_models":
        required = {"private", "public", "outside", "fallback"}
        deadline = time.monotonic() + 10
        attempts = 0
        while True:
            status, body = MODEL_GATEWAY.request("/v1/models", timeout=1)
            models = (
                sorted(row["id"] for row in body.get("data", []))
                if status == 200 and isinstance(body, dict)
                else []
            )
            attempts += 1
            ready = required.issubset(models)
            if ready or time.monotonic() >= deadline:
                return {
                    "ready": ready,
                    "status": status,
                    "model_ids": models,
                    "attempts": attempts,
                }
            time.sleep(0.1)
    elif action == "revoke":
        stores()[1].logout(credential["token"])
    elif action == "summary":
        return {
            "calls": rows("calls"),
            "decisions": rows("decisions"),
            "credential_headers": rows("credential_headers"),
            "provider_key_used": rows("provider_key_used"),
            "developer_key_forwarded": rows("developer_key_forwarded"),
            "tool_result_seen": rows("tool_result_seen"),
            "provider_actor": rows("provider_actor"),
            "forged_headers": rows("forged_headers"),
            "generation_forwarded": rows("generation_forwarded"),
            "settings": rows("settings"),
            "outage_steps": rows("outage_steps"),
        }
    elif action == "outage":
        steps = json.loads(arguments)
        allowed = {"ok", "slow", "context", "mid", "429", "500", "502", "503", "504"}
        assert isinstance(steps, list) and set(steps) <= allowed
        (STATE / "outage-script").write_text(json.dumps(steps))
    elif action == "protocol_failure":
        assert arguments in ("before", "mid")
        (STATE / "protocol-failure").write_text(arguments)
    elif action in ("actor_key_remove", "actor_key_replace", "actor_id"):
        from runtime_actor_keys import actors, change_key

        assert arguments in ("a", "b")
        if action == "actor_id":
            return actors(STATE)[arguments]["actor_id"]
        change_key(STATE, arguments, remove=action == "actor_key_remove")
    elif action in ("resource_revision", "publish_shared"):
        status, body = MODEL_GATEWAY.resources()
        assert status == 200
        previous = next(row for row in body["resources"] if row["id"] == "private")
        if action == "resource_revision":
            return previous["revision"]
        definition = previous["value"]
        target = str(Path("/trial") / os.environ["FIXTURE_PROVIDER_NEXT_KEY_NAME"])
        definition["auth"]["key"]["value"] = {"file": target}
        status, _ = MODEL_GATEWAY.request(
            "/api/config/resources/llm.model/private",
            {"value": definition},
            method="PUT",
        )
        assert status == 200
        status, body = MODEL_GATEWAY.resources()
        assert status == 200
        current = next(row for row in body["resources"] if row["id"] == "private")
        stores()[2].approve(
            "private",
            ["Confidential"],
            fingerprint("private", body["resources"]),
            key_choice="shared",
        )
        return {
            "before": previous["revision"],
            "after": current["revision"],
            "file_reference_matches": current["value"]["auth"]["key"]["value"]
            == {"file": target},
        }
    elif action == "config":
        status, body = MODEL_GATEWAY.request("/api/config")
        assert status == 200
        expected = json.loads(Path("/trial/gateway.yaml").read_text())["llm"]["models"]
        status, listing = MODEL_GATEWAY.models()
        assert status == 200
        return {
            "hash": hashlib.sha256(
                json.dumps(body, sort_keys=True).encode()
            ).hexdigest(),
            "existing_preserved": all(
                model in body["llm"]["models"] for model in expected
            ),
            "existing_listed": any(
                model["id"] == "customer-owned" for model in listing["data"]
            ),
        }
    elif action == "reset":
        for name in (
            "calls",
            "decisions",
            "credential_headers",
            "provider_key_used",
            "developer_key_forwarded",
            "tool_result_seen",
            "provider_actor",
            "forged_headers",
            "generation_forwarded",
            "settings",
            "protocol-failure",
            "outage-script",
            "outage_steps",
        ):
            (STATE / name).unlink(missing_ok=True)


if __name__ == "__main__":
    if sys.argv[1] == "serve":
        serve()
    else:
        print(
            json.dumps(command(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else ""))
        )
