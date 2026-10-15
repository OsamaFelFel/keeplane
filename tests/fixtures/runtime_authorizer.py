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
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        append("calls", body["model"])
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
    password = "isolated-runtime-developer-password"
    actor = identity.create_user(
        {"username": "runtime-fixture", "password": password, "role": "developer"}
    )
    token, project = identity.login(actor["username"], password), str(uuid.uuid4())
    DjangoProjectStore().register_use(actor["id"], project, "Native authorization")
    classes.set_enabled(True)
    ProjectClass.objects.create(project_id=project, data_class_id="confidential")
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
    for name, approved in (("private", ["Confidential"]), ("public", ["Public"])):
        catalog.approve(name, approved, fingerprint(name, resource_body["resources"]))
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
    elif action == "revoke":
        stores()[1].logout(credential["token"])
    elif action == "summary":
        return {
            "calls": rows("calls"),
            "decisions": rows("decisions"),
            "credential_headers": rows("credential_headers"),
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
        for name in ("calls", "decisions", "credential_headers"):
            (STATE / name).unlink(missing_ok=True)


if __name__ == "__main__":
    if sys.argv[1] == "serve":
        serve()
    else:
        print(
            json.dumps(command(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else ""))
        )
