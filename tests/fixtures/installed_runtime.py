"""Disposable actual-installer bootstrap; never mounted in a developer client."""

import json
import os
import secrets
import threading
import time
import uuid
from http.cookies import SimpleCookie
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.request import Request, urlopen
from wsgiref.simple_server import WSGIRequestHandler, make_server


class Silent(WSGIRequestHandler):
    def log_message(self, *args):
        pass


def bootstrap(provider_handler):
    """Seed a synthetic shared model, then invoke the real management command."""
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    import django

    django.setup()
    from common.api import MODEL_GATEWAY
    from common.stores import stores
    from data_classes.models import ProjectClass
    from django.core.management import call_command
    from django.core.wsgi import get_wsgi_application
    from projects.services import DjangoProjectStore

    call_command("migrate", verbosity=0)
    _, identity, _, classes = stores()
    accounts = {}
    for label in ("a", "b"):
        password = secrets.token_urlsafe(24)
        actor = identity.create_user(
            {
                "username": "installed-" + label,
                "role": "developer",
                "password": password,
            }
        )
        accounts[label] = dict(actor, password=password)
    project = str(uuid.uuid4())
    DjangoProjectStore().register_use(accounts["a"]["id"], project, "Installed coding")
    classes.set_enabled(True)
    ProjectClass.objects.create(project_id=project, data_class_id="confidential")

    key = Path(os.environ["PROVIDER_KEY_DIR"]) / os.environ["KEY_NAME"]
    provider_handler.grant = key.read_text().strip()
    provider_handler.target = Path("/client/project/math.py")
    provider_handler.required_instruction = None
    provider_handler.turn_scoped = True
    provider_handler.calls = []
    provider = ThreadingHTTPServer(("0.0.0.0", 18080), provider_handler)
    threading.Thread(target=provider.serve_forever, daemon=True).start()
    application = get_wsgi_application()
    server = make_server("0.0.0.0", 8090, application, handler_class=Silent)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    for _ in range(100):
        try:
            status, _ = MODEL_GATEWAY.request(
                "/api/config", timeout=2, connection_retries=0
            )
            if status == 200:
                break
        except OSError:
            pass
        time.sleep(0.1)
    else:
        raise RuntimeError("Disposable gateway was not ready")
    # Exercise the actual administration API, including CSRF and native model
    # validation. The synthetic operator keeps its cookie only in this process.
    cookies = {}
    origin = os.environ.get("PUBLIC_ORIGIN", "http://127.0.0.1:8090")

    def admin(path, body=None):
        with urlopen(
            Request(
                "http://127.0.0.1:8090/api/auth-options",
                headers={"Host": origin.split("://", 1)[1]},
            ),
            timeout=5,
        ) as response:
            csrf = json.load(response)["csrf_token"]
            for header in response.headers.get_all("Set-Cookie", []):
                parsed = SimpleCookie()
                parsed.load(header)
                cookies.update({name: value.value for name, value in parsed.items()})
        headers = {
            "Origin": origin,
            "Host": origin.split("://", 1)[1],
            "Content-Type": "application/json",
            "X-Keeplane-Action": "1",
            "X-CSRFToken": csrf,
            "Cookie": "; ".join(name + "=" + value for name, value in cookies.items()),
        }
        request = Request(
            "http://127.0.0.1:8090" + path,
            data=None if body is None else json.dumps(body).encode(),
            headers=headers,
        )
        with urlopen(request, timeout=30) as response:
            for header in response.headers.get_all("Set-Cookie", []):
                parsed = SimpleCookie()
                parsed.load(header)
                cookies.update({name: value.value for name, value in parsed.items()})
            if response.status != 200:
                raise RuntimeError("Disposable admin setup failed")
            return json.load(response)

    admin(
        "/api/session",
        {
            "username": "first-admin",
            "password": Path(os.environ["FIRST_ADMIN_PASSWORD_FILE"])
            .read_text()
            .strip(),
        },
    )
    admin(
        "/api/models",
        {
            "name": "shared",
            "model": "fixture-coder",
            "source": "openai",
            "key_choice": "shared",
            "shared_key": provider_handler.grant,
            "approved_classes": ["Confidential"],
        },
    )
    admin("/sign-out", {})
    # The command uses loopback admin from the same network namespace. Only the
    # server fixture has the installation volume and provider credential.
    call_command(
        "install_runtime_guard",
        model=["shared"],
        trusted_file=os.environ.get("FIXTURE_TRUSTED_FILE", "/installed/trusted.json"),
        callback_host="127.0.0.1:8090",
        verbosity=0,
    )
    return {
        "server": os.environ.get("PUBLIC_ORIGIN", "http://127.0.0.1:8090"),
        "model": "shared",
        "project_id": project,
        "accounts": {
            label: {key: row[key] for key in ("id", "username", "password")}
            for label, row in accounts.items()
        },
    }


def serve(provider_handler):
    seed = bootstrap(provider_handler)
    ready = Path("/state/ready.json")
    ready.write_text(json.dumps(seed))
    ready.chmod(0o600)
    while True:
        time.sleep(1)
