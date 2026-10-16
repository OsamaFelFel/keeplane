"""Exercise packaged imports, migrations, accounts and Gunicorn without a gateway."""

import importlib
import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import urlopen

sys.path.insert(0, "/app")
for name in ("pip", "ensurepip"):
    assert importlib.util.find_spec(name) is None, name
assert not any(Path("/usr/local/bin").glob("pip*"))
for name in (
    "_sqlite3",
    "_ssl",
    "_ctypes",
    "_lzma",
    "_gdbm",
    "readline",
    "django",
    "rest_framework",
    "gunicorn",
    "asgiref",
    "sqlparse",
    "packaging",
):
    importlib.import_module(name)
notices = next(Path("/usr/share/keeplane/licenses").glob("pip-*"))
assert (notices / "licenses/LICENSE.txt").is_file()
assert (notices / "licenses/src/pip/_vendor/requests/LICENSE").is_file()
assert (notices / "METADATA").is_file() and (notices / "vendor.txt").is_file()
if sys.argv[1] == "postgres":
    from django.db.backends.postgresql.base import Database

    assert Database.pq.__impl__ == "c"
    assert Database.pq.version() >= 180006
    package = Path("/usr/share/keeplane")
    assert len(list((package / "sources").glob("psycopg*"))) == 2
    assert (package / "postgres-package.json").is_file()
else:
    assert importlib.util.find_spec("psycopg") is None

Path("/state/signing").write_text("isolated-runtime-fixture-signing-secret-" * 2)
os.environ.update(
    DJANGO_SECRET_KEY_FILE="/state/signing", DJANGO_SETTINGS_MODULE="config.settings"
)
for command in (
    ("check",),
    ("migrate", "--noinput"),
    ("makemigrations", "--check", "--dry-run"),
):
    subprocess.run([sys.executable, "/app/manage.py", *command], check=True, timeout=60)
import django

django.setup()
from accounts.models import User
from django.contrib.sessions.backends.db import SessionStore

user = User(username="runtime-fixture", role="developer")
user.set_password("synthetic-runtime-password-123")
user.save()
assert User.objects.get(pk=user.pk).check_password("synthetic-runtime-password-123")
session = SessionStore()
session["runtime_fixture"] = str(user.pk)
session.save()
assert SessionStore(session_key=session.session_key)["runtime_fixture"] == str(user.pk)

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
        for attempt in range(50):
            try:
                with urlopen(
                    "http://127.0.0.1:3000/health/ready", timeout=1
                ) as response:
                    assert json.load(response) == {"app": "ready"}
                break
            except OSError:
                if process.poll() is not None:
                    log.seek(0)
                    raise RuntimeError(log.read())
                time.sleep(0.1)
        else:
            raise RuntimeError("Gunicorn readiness timed out")
    finally:
        process.terminate()
        process.wait(timeout=10)
print("Runtime imports, notices, migrations, accounts, sessions and Gunicorn passed")
