"""Run inside the real combined image; never install or overlay app packages."""

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
seed = json.load(sys.stdin)
assert os.geteuid() == 65532
for name in ("pip", "ensurepip"):
    assert importlib.util.find_spec(name) is None
assert not any(Path("/usr/local/bin").glob("pip*"))
for key in ("password", "signing"):
    path = Path("/state") / key
    path.write_text(seed[key])
    path.chmod(0o600)
os.environ.update(
    DJANGO_SETTINGS_MODULE="config.settings",
    DJANGO_SECRET_KEY_FILE="/state/signing",
    KEEPLANE_DATABASE_HOST="database",
    KEEPLANE_DATABASE_NAME="keeplane",
    KEEPLANE_DATABASE_USER="keeplane",
    KEEPLANE_DATABASE_PASSWORD_FILE="/state/password",
    KEEPLANE_DATABASE_SSLMODE="disable",
    KEEPLANE_CLI_OAUTH_ENABLED="1",
    PUBLIC_ORIGIN="https://keeplane.example.test",
)
import django

django.setup()
from django.db import connection
from django.db.backends.postgresql.base import Database
from oauth2_provider.models import Application

assert connection.vendor == "postgresql"
assert Database.pq.__impl__ == "c" and Database.pq.version() >= 180006
assert importlib.metadata.version("django-oauth-toolkit") == "3.4.1"
package = Path("/usr/share/keeplane")
assert (package / "postgres-package.json").is_file()
assert len(list((package / "sources").glob("psycopg*"))) == 2
assert next((package / "licenses").glob("pip-*/licenses/LICENSE.txt")).is_file()
pins = json.loads(Path("/app/licenses/cli-auth-trial.json").read_text())
for item in pins["packages"]:
    assert importlib.metadata.version(item["name"]) == item["version"]
    for name, expected in item["notices"].items():
        location = (
            Path("/usr/local") / name.split(".data/data/", 1)[1]
            if ".data/data/" in name
            else Path("/usr/local/lib/python3.13/site-packages") / name
        )
        assert hashlib.sha256(location.read_bytes()).hexdigest() == expected
for arguments in (
    ("check",), ("migrate", "--noinput"),
    ("makemigrations", "--check", "--dry-run"),
    ("register_cli_client",), ("register_cli_client", "--device"),
    ("register_cli_client",), ("register_cli_client", "--device"),
):
    subprocess.run([sys.executable, "/app/manage.py", *arguments], check=True, timeout=60)
clients = list(Application.objects.order_by("client_id").values_list("client_id", flat=True))
assert clients == ["keeplane-cli", "keeplane-cli-device"]
assert all(item.client_type == Application.CLIENT_PUBLIC and not item.skip_authorization
           for item in Application.objects.all())
with Path("/state/gunicorn.log").open("w+") as log:
    process = subprocess.Popen(
        ["gunicorn", "--config", "/app/config/gunicorn.conf.py", "config.wsgi:application"],
        stdout=log, stderr=log,
    )
    try:
        for _ in range(100):
            try:
                with urlopen("http://127.0.0.1:3000/health/ready", timeout=1) as response:
                    assert json.load(response) == {"app": "ready"}
                break
            except OSError:
                if process.poll() is not None:
                    log.seek(0)
                    raise RuntimeError(log.read())
                time.sleep(0.1)
        else:
            raise RuntimeError("Combined image did not become ready")
    finally:
        process.terminate()
        process.wait(timeout=10)
print(json.dumps({"uid": os.geteuid(), "postgres_impl": Database.pq.__impl__,
                  "toolkit": importlib.metadata.version("django-oauth-toolkit"),
                  "clients": clients, "ready": True, "installers_absent": True}))
