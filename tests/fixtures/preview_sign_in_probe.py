"""Run inside the built preview image; never install or overlay app packages.

Case PSIMG-01 in tests/integration/preview-sign-in-image-cases.md. Checks the
hash-pinned sign-in packages and their original wheel notices, then migrates a
new SQLite database, registers both fixed CLI clients twice and requires
Gunicorn's readiness answer with CLI sign-in on.
"""

import hashlib
import importlib.metadata
import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import urlopen

sys.path.insert(0, "/app")
assert os.geteuid() == 65532
for name in ("pip", "ensurepip"):
    assert importlib.util.find_spec(name) is None
assert not any(Path("/usr/local/bin").glob("pip*"))
for name in ("_cffi_backend", "cryptography.hazmat.bindings._rust"):
    importlib.import_module(name)
Path("/state/signing").write_text("probe-" + os.urandom(24).hex())
Path("/state/database").mkdir(mode=0o700)
os.environ.update(
    DJANGO_SETTINGS_MODULE="config.settings",
    DJANGO_SECRET_KEY_FILE="/state/signing",
    KEEPLANE_SQLITE_PATH="/state/database/keeplane.sqlite3",
    KEEPLANE_CLI_OAUTH_ENABLED="1",
    PUBLIC_ORIGIN="http://127.0.0.1:3000",
)
import django

django.setup()
from django.db import connection
from oauth2_provider.models import Application

assert connection.vendor == "sqlite"
assert importlib.metadata.version("django-oauth-toolkit") == "3.4.1"
assert next(
    Path("/usr/share/keeplane/licenses").glob("pip-*/licenses/LICENSE.txt")
).is_file()
pins = json.loads(Path("/app/licenses/cli-auth-trial.json").read_text())
notices = 0
for item in pins["packages"]:
    assert importlib.metadata.version(item["name"]) == item["version"], item["name"]
    for name, expected in item["notices"].items():
        location = (
            Path("/usr/local") / name.split(".data/data/", 1)[1]
            if ".data/data/" in name
            else Path("/usr/local/lib/python3.13/site-packages") / name
        )
        assert hashlib.sha256(location.read_bytes()).hexdigest() == expected, name
        notices += 1
for arguments in (
    ("check",),
    ("migrate", "--noinput"),
    ("makemigrations", "--check", "--dry-run"),
    ("register_cli_client",),
    ("register_cli_client", "--device"),
    ("register_cli_client",),
    ("register_cli_client", "--device"),
):
    subprocess.run(
        [sys.executable, "/app/manage.py", *arguments],
        check=True,
        timeout=60,
        stdout=subprocess.DEVNULL,
    )
clients = list(
    Application.objects.order_by("client_id").values_list("client_id", flat=True)
)
assert clients == ["keeplane-cli", "keeplane-cli-device"]
assert all(
    item.client_type == Application.CLIENT_PUBLIC and not item.skip_authorization
    for item in Application.objects.all()
)
with Path("/state/gunicorn.log").open("w+") as log:
    process = subprocess.Popen(
        [
            "gunicorn",
            "--config",
            "/app/config/gunicorn.conf.py",
            "config.wsgi:application",
        ],
        stdout=log,
        stderr=log,
    )
    try:
        for _ in range(100):
            try:
                with urlopen(
                    "http://127.0.0.1:3000/health/ready", timeout=1
                ) as response:
                    assert json.load(response) == {"app": "ready"}
                break
            except OSError:
                if process.poll() is not None:
                    log.seek(0)
                    raise RuntimeError(log.read()) from None
                time.sleep(0.1)
        else:
            raise RuntimeError("The preview image did not become ready")
    finally:
        process.terminate()
        process.wait(timeout=10)
print(
    json.dumps(
        {
            "uid": os.geteuid(),
            "database": connection.vendor,
            "toolkit": importlib.metadata.version("django-oauth-toolkit"),
            "packages": len(pins["packages"]),
            "notices": notices,
            "clients": clients,
            "ready": True,
            "installers_absent": True,
        }
    )
)
