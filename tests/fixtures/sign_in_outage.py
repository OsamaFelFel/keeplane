"""A disposable PostgreSQL install for the sign-in restart and outage cases.

For tests/e2e/sign-in-restart-outage-cases.md; never use for deployment. The
host side (`Stack`) writes and runs its own Compose project, on loopback ports
the system picks, so it never touches the local preview on port 3000:

- `database`: PostgreSQL, with its data on a volume, so a restart keeps it;
- `app`: the PostgreSQL app image with CLI sign-in, served by gunicorn as in
  a release, after `app-setup` has migrated and registered the CLI clients;
- `gateway`: a pinned agentgateway, set up as a customer runs it, whose
  developer route asks the app's route check before every model call;
- `model`: a mock OpenAI-compatible provider.

Inside the app container, `python /fixture.py register-model NAME` adds the
customer's model to the gateway as the customer would, through its management
API; the gateway keeps it on a volume, so a restart keeps it. As the `model`
service, `python /fixture.py provider` serves the mock.
"""

import hashlib
import json
import os
import secrets
import socket
import subprocess
import sys
import time
import uuid
from html.parser import HTMLParser
from http.cookiejar import CookieJar
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import (
    HTTPCookieProcessor,
    HTTPRedirectHandler,
    ProxyHandler,
    Request,
    build_opener,
)

# In a container this file is /fixture.py, which has no repo around it.
ROOT = (
    Path(__file__).resolve().parents[min(2, len(Path(__file__).resolve().parents) - 1)]
)
MODEL = "coder"
# Never a Keeplane header at the provider.
FORWARD_NEVER = [
    "authorization",
    "x-keeplane-gateway-credential",
    "x-keeplane-project-id",
]


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def model_definition(name):
    return {
        "id": name,
        "name": name,
        "provider": {"custom": {"formats": [{"type": "completions"}]}},
        "params": {"model": "mock-" + name, "baseUrl": "http://model:18080/v1"},
        "requestHeaders": {"remove": FORWARD_NEVER},
    }


def gateway_config(admin_key):
    """The customer's gateway: Keeplane's route check on the developer route."""
    route_check = {
        "host": "app:3000",
        "failureMode": "deny",
        "includeRequestHeaders": ["authorization"],
        "policies": {
            "backendAuth": {
                "key": {
                    "value": {"file": "/trial/gateway-key"},
                    "location": {
                        "header": {
                            "name": "x-keeplane-gateway-credential",
                            "prefix": "",
                        }
                    },
                }
            }
        },
        "protocol": {
            "http": {
                "path": '"/internal/runtime/authorize"',
                "addRequestHeaders": {
                    "content-type": '"application/json"',
                    ":method": '"POST"',
                },
                "body": '{"project_id": request.headers["x-keeplane-project-id"], '
                '"model_id": json(request.body).model}',
            }
        },
    }
    return {
        "config": {
            "adminAddr": "127.0.0.1:15000",
            "statsAddr": "127.0.0.1:15020",
            "readinessAddr": "127.0.0.1:15021",
            "storage": {"mode": "hybrid"},
            "database": {"url": "sqlite:///data/gateway.db"},
            "sensitiveHeaders": ["authorization", "x-keeplane-gateway-credential"],
        },
        # The model port: Keeplane's management and setup calls, with its keys.
        "gateways": {"default": {"port": 4000, "bindAddress": "0.0.0.0"}},
        "ui": {
            "gateways": "default",
            "policies": {
                "apiKey": {
                    "mode": "strict",
                    "keys": [
                        {
                            "keyHash": "sha256:"
                            + hashlib.sha256(admin_key.encode()).hexdigest()
                        }
                    ],
                }
            },
        },
        "binds": [
            {
                "port": 5000,
                "listeners": [
                    {
                        "name": "developer-chat",
                        "protocol": "HTTP",
                        "routes": [
                            {
                                "matches": [
                                    {"path": {"exact": "/v1/chat/completions"}}
                                ],
                                "backends": [{"host": "127.0.0.1:4000"}],
                                "policies": {"extAuthz": route_check},
                            }
                        ],
                    }
                ],
            }
        ],
    }


class Stack:
    """The disposable install. Use it as a context manager."""

    def __init__(self, directory, image):
        self.directory = directory
        self.project = "keeplane-sign-in-outage-" + uuid.uuid4().hex[:10]
        self.app_port, self.gateway_port = free_port(), free_port()
        while self.gateway_port == self.app_port:
            self.gateway_port = free_port()
        self.server = f"http://127.0.0.1:{self.app_port}"
        self.gateway = f"http://127.0.0.1:{self.gateway_port}/v1"
        images = json.loads((ROOT / "deploy/local/stack.lock.json").read_text())[
            "images"
        ]
        trial = directory / "trial"
        trial.mkdir(mode=0o755)
        self.values = {
            "admin": secrets.token_urlsafe(32),
            "gateway-key": secrets.token_urlsafe(32),
            "first-admin": secrets.token_urlsafe(32),
            "signing": secrets.token_urlsafe(64),
            "database-password": secrets.token_urlsafe(24),
        }
        for name, value in self.values.items():
            (trial / name).write_text(value)
            # Synthetic values inside pytest's private parent, read by other users.
            (trial / name).chmod(0o644)
        (trial / "gateway.yaml").write_text(
            json.dumps(gateway_config(self.values["admin"]))
        )
        image_id = self.command(
            "docker", "image", "inspect", image, "--format", "{{.Id}}"
        )
        mounts = [str(trial) + ":/trial:ro"]
        fixture = str(Path(__file__).resolve()) + ":/fixture.py:ro"
        app_environment = {
            "PYTHONPATH": "/app",
            "PYTHONDONTWRITEBYTECODE": "1",
            "GATEWAY_MODE": "existing",
            "DJANGO_SECRET_KEY_FILE": "/trial/signing",
            "FIRST_ADMIN_PASSWORD_FILE": "/trial/first-admin",
            "PUBLIC_ORIGIN": self.server,
            "GATEWAY_URL": "http://gateway:4000",
            "GATEWAY_ADMIN_KEY_FILE": "/trial/admin",
            "GATEWAY_RUNTIME_KEY_FILE": "/trial/admin",
            "RUNTIME_AUTHORIZER_KEY_FILE": "/trial/gateway-key",
            "KEEPLANE_CLI_OAUTH_ENABLED": "1",
            "KEEPLANE_GATEWAY_PUBLIC_URL": self.gateway,
            # The production storage settings: the app's own database user and
            # a password file. TLS to PostgreSQL is checked by the chart and
            # deployment cases; this disposable network has no certificates.
            "KEEPLANE_DATABASE_HOST": "database",
            "KEEPLANE_DATABASE_NAME": "keeplane",
            "KEEPLANE_DATABASE_USER": "keeplane",
            "KEEPLANE_DATABASE_PASSWORD_FILE": "/trial/database-password",
            "KEEPLANE_DATABASE_SSLMODE": "disable",
        }
        app = {
            "image": image_id,
            "volumes": mounts
            + [str(ROOT / "components/control-plane") + ":/app:ro", fixture],
            "environment": app_environment,
            "read_only": True,
            "tmpfs": ["/tmp:uid=65532,gid=65532,mode=700"],
        }
        setup = (
            "python manage.py migrate --noinput && python manage.py bootstrap"
            " && python manage.py register_cli_client"
            " && python manage.py register_cli_client --device"
        )
        services = {
            "database": {
                "image": images["postgres"],
                "environment": {
                    "POSTGRES_USER": "keeplane",
                    "POSTGRES_DB": "keeplane",
                    "POSTGRES_PASSWORD_FILE": "/trial/database-password",
                },
                # On a volume, so a restart keeps every sign-in.
                "volumes": mounts + ["database-data:/var/lib/postgresql"],
                "healthcheck": {
                    "test": ["CMD", "pg_isready", "-U", "keeplane", "-d", "keeplane"],
                    "interval": "1s",
                    "retries": 60,
                },
            },
            "app-setup": {
                **app,
                "command": ["sh", "-ec", setup],
                "depends_on": {"database": {"condition": "service_healthy"}},
            },
            "app": {
                **app,
                "depends_on": {
                    "database": {"condition": "service_healthy"},
                    "app-setup": {"condition": "service_completed_successfully"},
                },
                "ports": [f"127.0.0.1:{self.app_port}:3000"],
            },
            "gateway": {
                "image": images["agentgateway"],
                "command": ["-f", "/trial/gateway.yaml"],
                "read_only": True,
                # On a volume, so a restart keeps the customer's models.
                "volumes": mounts + ["gateway-data:/data"],
                "depends_on": {
                    "gateway-volume": {"condition": "service_completed_successfully"}
                },
                # The disposable network is IPv4 only.
                "environment": {"IPV6_ENABLED": "false"},
                "ports": [f"127.0.0.1:{self.gateway_port}:5000"],
            },
            "gateway-volume": {
                "image": images["python_fixture"],
                "user": "0",
                "command": ["chown", "65532:65532", "/data"],
                "volumes": ["gateway-data:/data"],
            },
            "model": {
                "image": images["python_fixture"],
                "command": ["python", "/fixture.py", "provider"],
                "volumes": [fixture],
                "read_only": True,
                "tmpfs": ["/state:mode=700"],
            },
        }
        for name, service in services.items():
            service.update(
                {"pull_policy": "never", "security_opt": ["no-new-privileges:true"]}
            )
            if name not in ("database", "gateway-volume"):
                # PostgreSQL's entrypoint, and chown, need their default capabilities.
                service["cap_drop"] = ["ALL"]
        self.compose_file = directory / "compose.json"
        self.compose_file.write_text(
            json.dumps(
                {
                    "services": services,
                    "volumes": {"database-data": {}, "gateway-data": {}},
                }
            )
        )
        self.started = False

    def redact(self, text):
        for value in self.values.values():
            text = text.replace(value, "[redacted]")
        return text

    def command(self, *args, check=True, timeout=240, **kwargs):
        result = subprocess.run(
            args, check=False, capture_output=True, text=True, timeout=timeout, **kwargs
        )
        if check and result.returncode:
            raise RuntimeError(
                "Disposable fixture command failed: "
                + self.redact(result.stderr + result.stdout)[-2000:]
            )
        return result.stdout.strip()

    def compose(self, *args, **kwargs):
        return self.command(
            "docker",
            "compose",
            "-p",
            self.project,
            "-f",
            str(self.compose_file),
            *args,
            **kwargs,
        )

    def __enter__(self):
        self.started = True
        self.compose("up", "-d", "--wait", "database", "model", "gateway", timeout=300)
        self.compose("up", "-d", "app", timeout=300)
        self.wait_ready()
        self.compose(
            "exec", "-T", "app", "python", "/fixture.py", "register-model", MODEL
        )
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        if self.started:
            self.compose(
                "down", "--volumes", "--remove-orphans", check=False, timeout=180
            )
            self.started = False

    def logs(self, tail=60):
        return self.redact(
            self.compose("logs", "--no-color", "--tail", str(tail), check=False)
        )

    # Restarts and outages ------------------------------------------------

    def stop(self, service):
        self.compose("stop", "--timeout", "10", service)

    def start(self, service):
        self.compose("start", service)
        if service == "database":
            self.wait_database()
        elif service == "app":
            self.wait_ready()
        elif service == "gateway":
            self.wait_gateway()

    def restart(self, service):
        self.stop(service)
        self.start(service)

    def wait_database(self, timeout=60):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            ready = self.compose(
                "exec",
                "-T",
                "database",
                "pg_isready",
                "-U",
                "keeplane",
                "-d",
                "keeplane",
                check=False,
            )
            if "accepting connections" in ready:
                return
            time.sleep(0.5)
        raise RuntimeError("PostgreSQL did not come back")

    def wait_ready(self, timeout=120):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.status("/health/ready") == 200:
                return
            time.sleep(0.5)
        raise RuntimeError("The app did not become ready:\n" + self.logs())

    def wait_gateway(self, timeout=60):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                with build_opener(ProxyHandler({})).open(
                    self.gateway + "/models", timeout=2
                ):
                    return
            except HTTPError as error:
                error.close()
                return  # Listening: any HTTP answer will do.
            except (URLError, OSError):
                time.sleep(0.5)
        raise RuntimeError("The gateway did not come back")

    def status(self, path):
        try:
            with build_opener(ProxyHandler({})).open(
                self.server + path, timeout=3
            ) as response:
                return response.status
        except HTTPError as error:
            error.close()
            return error.code
        except (URLError, OSError):
            return None

    # What an admin and the provider see ------------------------------------

    def admin(self, method, path, body=None):
        """One request as the signed-in first admin, as the admin's browser sends it."""
        opener = build_opener(ProxyHandler({}), HTTPCookieProcessor(CookieJar()))

        def call(method, path, body=None):
            headers = {"Accept": "application/json", "Origin": self.server}
            if method != "GET":
                with opener.open(
                    self.server + "/api/auth-options", timeout=30
                ) as response:
                    headers["X-CSRFToken"] = json.load(response)["csrf_token"]
                headers.update(
                    {"Content-Type": "application/json", "X-Keeplane-Action": "1"}
                )
            sent = Request(
                self.server + path,
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
                error.close()
                try:
                    return error.code, json.loads(raw)
                except ValueError:
                    return error.code, None

        status, _ = call(
            "POST",
            "/api/session",
            {"username": "first-admin", "password": self.values["first-admin"]},
        )
        if status != 200:
            raise RuntimeError(f"The first admin could not sign in: HTTP {status}")
        return call(method, path, body)

    def provider_calls(self):
        """How many requests reached the mock provider since it started."""
        return int(self.compose("exec", "-T", "model", "cat", "/state/calls") or 0)

    def sql(self, statement):
        """One read-only query as the database owner; the result's rows as text."""
        return self.compose(
            "exec",
            "-T",
            "database",
            "psql",
            "-U",
            "keeplane",
            "-d",
            "keeplane",
            "-Atc",
            statement,
        )


# The developer's browser -------------------------------------------------


class _NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


class _HiddenFields(HTMLParser):
    def __init__(self):
        super().__init__()
        self.values = {}

    def handle_starttag(self, tag, attributes):
        values = dict(attributes)
        if tag == "input" and values.get("type") == "hidden" and "name" in values:
            self.values[values["name"]] = values.get("value", "")


class _Page:
    """A browser with cookies, on Keeplane's real sign-in and consent pages."""

    def __init__(self, server):
        self.server = server
        self.opener = build_opener(
            ProxyHandler({}), HTTPCookieProcessor(CookieJar()), _NoRedirects()
        )

    def open(self, target, data=None, *, expected=200, csrf=None):
        headers = {"Origin": self.server}
        if csrf:
            headers.update(
                {
                    "Content-Type": "application/json",
                    "X-CSRFToken": csrf,
                    "X-Keeplane-Action": "1",
                }
            )
            payload = json.dumps(data).encode()
        else:
            payload = None if data is None else urlencode(data).encode()
        if target.startswith("/"):
            target = self.server + target
        try:
            with self.opener.open(
                Request(target, payload, headers), timeout=10
            ) as response:
                status, raw, answer = (
                    response.status,
                    response.read(65536),
                    response.headers,
                )
        except HTTPError as error:
            try:
                status, raw, answer = error.code, error.read(65536), error.headers
            finally:
                error.close()
        if status != expected:
            raise RuntimeError(f"{urlsplit(target).path} answered {status}")
        return raw.decode("utf-8", "replace"), answer

    def sign_in(self, username, password):
        raw, _ = self.open("/api/auth-options")
        self.open(
            "/api/session",
            {"username": username, "password": password},
            csrf=json.loads(raw)["csrf_token"],
        )


def wait_for(control, stage):
    """Say the browser reached ``stage``, then wait until the case lets it go on."""
    (control / (stage + ".reached")).touch()
    deadline = time.monotonic() + 120
    while not (control / (stage + ".go")).exists():
        if time.monotonic() > deadline:
            raise RuntimeError("The case never let the browser go on")
        time.sleep(0.05)


def browser(url):
    """The CLI's browser: sign in, allow CLI access, return to the CLI.

    Run as the CLI's BROWSER command. ``KEEPLANE_FIXTURE_LOGIN`` names a file
    with the server, the developer's name and password, the control folder and
    the stages to stop at: "page", with the consent page open, and "callback",
    after allowing access and before the browser returns to the CLI.
    """
    login = json.loads(Path(os.environ["KEEPLANE_FIXTURE_LOGIN"]).read_text())
    control, stops = Path(login["control"]), set(login.get("stops", ()))
    page = _Page(login["server"])
    _, headers = page.open(url, expected=302)
    returned = parse_qs(urlsplit(headers["Location"]).query)["return_to"][0]
    page.sign_in(login["username"], login["password"])
    consent, _ = page.open(returned)
    if "Allow CLI access?" not in consent:
        raise RuntimeError("No consent page")
    if "page" in stops:
        wait_for(control, "page")
    fields = _HiddenFields()
    fields.feed(consent)
    fields.values["allow"] = "true"
    _, headers = page.open("/oauth/authorize/", fields.values, expected=302)
    callback = headers["Location"]
    if urlsplit(callback).hostname != "127.0.0.1":
        raise RuntimeError("Not the CLI's own callback")
    if "callback" in stops:
        wait_for(control, "callback")
    page.open(callback)


def approve_device(server, username, password, code):
    """Enter the CLI's code on the device pages and allow CLI access."""
    page = _Page(server)
    page.sign_in(username, password)
    form, _ = page.open("/oauth/confirm-device/?" + urlencode({"user_code": code}))
    fields = _HiddenFields()
    fields.feed(form)
    fields.values["user_code"] = code
    _, headers = page.open("/oauth/confirm-device/", fields.values, expected=302)
    consent, _ = page.open(headers["Location"])
    if "Allow CLI access?" not in consent:
        raise RuntimeError("No consent page")
    fields = _HiddenFields()
    fields.feed(consent)
    fields.values["action"] = "accept"
    done, _ = page.open("/oauth/confirm-device/", fields.values)
    return "CLI access allowed" in done


# Inside the containers ---------------------------------------------------


class Provider(BaseHTTPRequestHandler):
    """The mock provider: one short answer with usage, counting each call."""

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        calls = Path("/state/calls")
        calls.write_text(
            str(int(calls.read_text() or 0) + 1) if calls.exists() else "1"
        )
        leaked = sorted(
            name for name in FORWARD_NEVER if name in {k.lower() for k in self.headers}
        )
        data = json.dumps(
            {
                "id": "fixture",
                "object": "chat.completion",
                "model": body.get("model"),
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": "OK" if not leaked else "LEAK",
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 3,
                    "completion_tokens": 1,
                    "total_tokens": 4,
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


def register_model(name):
    """The customer adds its model to its own gateway, outside Keeplane."""
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    import django

    django.setup()
    from common.api import MODEL_GATEWAY

    status, _ = MODEL_GATEWAY.request(
        "/api/config/resources/llm.model",
        {"resources": [{"value": model_definition(name)}]},
        method="PUT",
    )
    if status != 200:
        raise SystemExit(f"The customer's model registration failed: HTTP {status}")


if __name__ == "__main__":
    if sys.argv[1] == "provider":
        Path("/state/calls").write_text("0")
        ThreadingHTTPServer(("0.0.0.0", 18080), Provider).serve_forever()
    elif sys.argv[1] == "register-model":
        register_model(sys.argv[2])
    else:
        raise SystemExit("Choose provider or register-model")
