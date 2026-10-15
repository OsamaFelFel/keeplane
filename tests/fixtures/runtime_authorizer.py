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


class Model(BaseHTTPRequestHandler):
    requires_key = False

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
        append("provider_key_used", key_matches)
        token = json.loads((STATE / "credential").read_text())["token"]
        append("developer_key_forwarded", token in authorization)
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
    classes.set_enabled(True)
    if not seeded:
        ProjectClass.objects.create(project_id=project, data_class_id="confidential")
    shared = os.environ.get("FIXTURE_SHARED_PROVIDER_KEY") == "1"
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
            definition["requestHeaders"]["remove"].remove("authorization")
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
    credential = STATE / "credential"
    credential.write_text(json.dumps({"token": token, "project": project}))
    credential.chmod(0o600)
    application = get_wsgi_application()

    def recorded(environ, start_response):
        raw = environ["wsgi.input"].read(int(environ.get("CONTENT_LENGTH") or 0))
        environ["wsgi.input"] = io.BytesIO(raw)
        metadata = json.loads(raw)
        # Store only the metadata contract, never headers or prompt text.
        append(
            "decisions",
            {
                "keys": sorted(metadata),
                "project_id": metadata.get("project_id"),
                "model_id": metadata.get("model_id"),
            },
        )
        return application(environ, start_response)

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
    elif action == "revoke":
        stores()[1].logout(credential["token"])
    elif action == "summary":
        return {
            "calls": rows("calls"),
            "decisions": rows("decisions"),
            "credential_headers": rows("credential_headers"),
            "provider_key_used": rows("provider_key_used"),
            "developer_key_forwarded": rows("developer_key_forwarded"),
        }
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
        ):
            (STATE / name).unlink(missing_ok=True)


if __name__ == "__main__":
    if sys.argv[1] == "serve":
        serve()
    else:
        print(
            json.dumps(command(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else ""))
        )
