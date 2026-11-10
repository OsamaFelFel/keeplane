"""Disposable Keeplane app and mock provider behind a customer-run gateway.

For the data-class mode cases (tests/integration/existing-gateway-class-mode-cases.md);
never use for deployment. `serve` runs the real Django app with
GATEWAY_MODE=existing on 127.0.0.1:8090, where the customer-run gateway's two
checks reach it, and a mock provider on 127.0.0.1:18080. Every other action
runs in its own process: `admin` makes one signed-in admin request to the
served app over HTTP, as the admin's browser does, so the switch and the
approvals reach the gateway's checks only through the shared database.
"""

import http.cookiejar
import io
import json
import os
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from socketserver import ThreadingMixIn
from urllib.error import HTTPError
from urllib.request import HTTPCookieProcessor, ProxyHandler, Request, build_opener
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django

django.setup()

from common.api import MODEL_GATEWAY
from common.stores import stores
from django.core.management import call_command
from django.core.wsgi import get_wsgi_application
from django.db import OperationalError, connection
from projects.services import DjangoProjectStore

STATE = Path("/state")
APP = "http://127.0.0.1:8090"
# Models the customer registers on its own gateway. Keeplane sets them up
# (or not) through its admin API; it never adds them to the gateway here.
MODELS = ("coder", "reviewer", "late-coder")
# The gateway's own setup check for Keeplane's model probe, which carries the
# gateway's runtime key rather than a developer session (see the cases).
SETUP_PROBE = "/internal/fixture/setup-probe"
FORWARD_NEVER = (
    "authorization",
    "x-keeplane-gateway-credential",
    "x-keeplane-project-id",
    "x-keeplane-developer-route",
)


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


class Provider(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        append("calls", body["model"])
        # Keeplane's headers must be removed before the provider.
        append(
            "forwarded",
            sorted(
                name
                for name in FORWARD_NEVER
                if name in {key.lower() for key in self.headers}
            ),
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


class Threaded(ThreadingMixIn, WSGIServer):
    # An admin's model setup calls the gateway, whose checks call back here.
    daemon_threads = True


class Silent(WSGIRequestHandler):
    def log_message(self, *args):
        pass


def definition(name):
    return {
        "id": name,
        "name": name,
        "provider": {"custom": {"formats": [{"type": "completions"}]}},
        "params": {"model": "mock-" + name, "baseUrl": "http://127.0.0.1:18080/v1"},
        "requestHeaders": {
            "remove": [
                "authorization",
                "x-keeplane-gateway-credential",
                "x-keeplane-project-id",
                "x-keeplane-developer-route",
            ]
        },
    }


def migrate():
    deadline = time.monotonic() + 60
    while True:
        try:
            call_command("migrate", verbosity=0)
            return
        except OperationalError:
            # PostgreSQL may still be starting; SQLite never waits here.
            if time.monotonic() > deadline:
                raise
            connection.close()
            time.sleep(1)


def wrap(application):
    admin_key = Path(os.environ["GATEWAY_RUNTIME_KEY_FILE"]).read_text().strip()

    def recorded(environ, start_response):
        path = environ.get("PATH_INFO", "")
        raw = environ["wsgi.input"].read(int(environ.get("CONTENT_LENGTH") or 0))
        environ["wsgi.input"] = io.BytesIO(raw)
        if path == SETUP_PROBE:
            # Only the app's own probe, with the gateway's runtime key.
            allowed = environ.get("HTTP_AUTHORIZATION") == "Bearer " + admin_key
            append("setup_probes", allowed)
            start_response(
                "200 OK" if allowed else "403 Forbidden",
                [("Content-Type", "application/json"), ("Content-Length", "2")],
            )
            return [b"{}"]
        if not path.startswith("/internal/runtime/authorize"):
            return application(environ, start_response)
        metadata = json.loads(raw or b"{}")

        def record(status, headers, exc_info=None):
            # The metadata contract only, never headers or prompt text.
            append(
                "decisions",
                {
                    "check": "final" if path.endswith("/selected") else "route",
                    "keys": sorted(metadata),
                    "project_id": metadata.get("project_id"),
                    "model_id": metadata.get("model_id"),
                    "status": int(status.split(" ", 1)[0]),
                },
            )
            return start_response(status, headers, exc_info)

        return application(environ, record)

    return recorded


def serve():
    migrate()
    _, identity, _, _ = stores()
    password = "class-mode-developer-password"
    actor = identity.create_user(
        {"username": "class-mode-developer", "password": password, "role": "developer"}
    )
    token = identity.login(actor["username"], password)
    projects = {"classed": str(uuid.uuid4()), "open": str(uuid.uuid4())}
    for key, name in (("classed", "Payments"), ("open", "Docs site")):
        DjangoProjectStore().register_use(actor["id"], projects[key], name)
    status, _ = MODEL_GATEWAY.request(
        "/api/config/resources/llm.model",
        {"resources": [{"value": definition(name)} for name in MODELS]},
        method="PUT",
    )
    if status != 200:
        raise RuntimeError("The customer's model registration failed")
    connection.close()
    credential = STATE / "credential"
    credential.write_text(
        json.dumps({"token": token, "project": projects["classed"], **projects})
    )
    credential.chmod(0o600)
    provider = ThreadingHTTPServer(("127.0.0.1", 18080), Provider)
    threading.Thread(target=provider.serve_forever, daemon=True).start()
    server = make_server(
        "127.0.0.1",
        8090,
        wrap(get_wsgi_application()),
        server_class=Threaded,
        handler_class=Silent,
    )
    (STATE / "ready").touch()
    server.serve_forever()


def admin(request):
    """One admin request through the served app, signed in as a browser is."""
    cookies = http.cookiejar.CookieJar()
    opener = build_opener(HTTPCookieProcessor(cookies))

    def call(method, path, body=None):
        headers = {"Accept": "application/json", "Origin": APP}
        if method != "GET":
            with opener.open(APP + "/api/auth-options", timeout=30) as response:
                headers["X-CSRFToken"] = json.load(response)["csrf_token"]
            headers.update(
                {"Content-Type": "application/json", "X-Keeplane-Action": "1"}
            )
        sent = Request(
            APP + path,
            None if body is None else json.dumps(body).encode(),
            headers,
            method=method,
        )
        try:
            with opener.open(sent, timeout=60) as response:
                raw = response.read()
                return response.status, json.loads(raw) if raw else None
        except HTTPError as error:
            raw = error.read()
            try:
                return error.code, json.loads(raw)
            except ValueError:
                return error.code, {"error": raw[:120].decode("utf-8", "replace")}

    password = Path(os.environ["FIRST_ADMIN_PASSWORD_FILE"]).read_text().strip()
    status, _ = call(
        "POST", "/api/session", {"username": "first-admin", "password": password}
    )
    if status != 200:
        raise RuntimeError(f"The admin could not sign in: HTTP {status}")
    status, body = call(request["method"], request["path"], request.get("body"))
    return {"status": status, "body": body}


def direct(request):
    """The developer's own session sent straight to the gateway's model port.

    Only Keeplane and the gateway share this network namespace; a developer
    can't reach it. This shows what the port's own check does if one could.
    """
    stored = json.loads((STATE / "credential").read_text())
    headers = {
        "Authorization": "Bearer " + stored["token"],
        "Content-Type": "application/json",
        "X-Keeplane-Project-ID": stored["classed"],
        **request.get("headers", {}),
    }
    sent = Request(
        "http://127.0.0.1:4000/v1/chat/completions",
        json.dumps(
            {
                "model": request["model"],
                "messages": [{"role": "user", "content": "synthetic"}],
            }
        ).encode(),
        headers,
    )
    try:
        with build_opener(ProxyHandler({})).open(sent, timeout=10) as response:
            return {"status": response.status}
    except HTTPError as error:
        return {"status": error.code}


def command(action, argument):
    if action == "admin":
        return admin(json.loads(argument))
    if action == "summary":
        return {
            "calls": rows("calls"),
            "decisions": rows("decisions"),
            "setup_probes": rows("setup_probes"),
            "forwarded": rows("forwarded"),
        }
    if action == "direct":
        return direct(json.loads(argument))
    if action == "reset":
        for name in ("calls", "decisions", "setup_probes", "forwarded"):
            (STATE / name).unlink(missing_ok=True)
        return {"reset": True}
    if action == "projects":
        stored = json.loads((STATE / "credential").read_text())
        return {"classed": stored["classed"], "open": stored["open"]}
    raise ValueError("Unknown fixture action")


if __name__ == "__main__":
    if sys.argv[1] == "serve":
        serve()
    else:
        print(
            json.dumps(command(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else ""))
        )
