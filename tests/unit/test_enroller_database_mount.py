"""The Docker preview's model enroller sees only the app database folder.

Cases EDM-01 to EDM-06 in enroller-database-mount-cases.md. The Compose
checks render compose.yaml with deploy/local/runtime.yaml through
`docker compose config`, which reads files only and starts nothing.
"""

import importlib.util
import json
import os
import shutil
import sqlite3
import stat
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DATABASE = "/state/database/keeplane.sqlite3"
DATABASE_USERS = ("app", "app-migrate", "runtime-install", "model-enroller")


@pytest.fixture(scope="module")
def rendered():
    if not shutil.which("docker"):
        if os.environ.get("CI"):
            pytest.fail("CI must render the preview's Compose files")
        pytest.skip("Docker Compose is not installed here")
    environment = dict(
        os.environ,
        GATEWAY_RUNTIME_KEY_HASH="synthetic",
        GATEWAY_ADMIN_KEY_HASH="synthetic",
    )
    result = subprocess.run(
        ["docker", "compose", "-f", "compose.yaml", "-f", "deploy/local/runtime.yaml",
         "--profile", "*", "config", "--format", "json"],
        cwd=ROOT, env=environment, capture_output=True, text=True, timeout=60, check=True,
    )
    return json.loads(result.stdout)["services"]


def account_mounts(service):
    return [row for row in service.get("volumes", []) if row["source"] == "account-data"]


def test_edm01_the_enroller_mounts_only_the_database_folder_read_only(rendered):
    enroller = rendered["model-enroller"]
    assert account_mounts(enroller) == [
        {
            "type": "volume",
            "source": "account-data",
            "target": "/state/database",
            "read_only": True,
            "volume": {"subpath": "database"},
        }
    ]
    # Nothing else of /state: no signing secret, no earlier preview files.
    targets = [row["target"] for row in enroller["volumes"]]
    assert "/state" not in targets
    assert not any(
        target.startswith("/state/") and target != "/state/database" for target in targets
    )
    assert enroller["environment"]["KEEPLANE_DATABASE_READ_ONLY"] == "1"
    assert enroller["environment"]["KEEPLANE_SQLITE_PATH"] == DATABASE
    assert str(Path(DATABASE).parent) == "/state/database"


def test_edm02_every_database_user_opens_the_same_file(rendered):
    for name in DATABASE_USERS:
        assert rendered[name]["environment"]["KEEPLANE_SQLITE_PATH"] == DATABASE, name
    # The writers keep the whole account volume; only the enroller is narrowed.
    for name in ("app", "app-migrate", "runtime-install", "account-volume-init"):
        mounts = account_mounts(rendered[name])
        assert [(row["target"], row.get("read_only", False)) for row in mounts] == [
            ("/state", False)
        ], name
    # No PostgreSQL mode in the Docker preview: nothing names a database server.
    for service in rendered.values():
        assert "KEEPLANE_DATABASE_HOST" not in service.get("environment", {})


def settings_process(probe, **values):
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("KEEPLANE_", "DJANGO_"))
    }
    environment.update(
        DJANGO_SETTINGS_MODULE="config.settings",
        PYTHONPATH=str(ROOT / "components/control-plane"),
        **values,
    )
    return subprocess.run(
        [sys.executable, "-c", probe],
        env=environment, capture_output=True, text=True, timeout=60, check=True,
    )


ENROLLER_SETTINGS = """
import django, json
django.setup()
from django.conf import settings
from django.core.management import call_command, load_command_class
load_command_class("model_registry", "run_model_enroller")
# The checks every management command runs before it starts.
call_command("check")
print(json.dumps([settings.DATABASES["default"]["NAME"], settings._wrapped.SECRET_KEY]))
"""


def test_edm03_the_enroller_starts_read_only_without_the_signing_secret(rendered):
    environment = rendered["model-enroller"]["environment"]
    # The enroller's mount has no /state/django-secret-key; it doesn't need one.
    name, secret = json.loads(
        settings_process(
            ENROLLER_SETTINGS,
            KEEPLANE_DATABASE_READ_ONLY=environment["KEEPLANE_DATABASE_READ_ONLY"],
            KEEPLANE_SQLITE_PATH=environment["KEEPLANE_SQLITE_PATH"],
            KEEPLANE_SECRET_KEY_FILE="/nonexistent/django-secret-key",
        ).stdout.splitlines()[-1]
    )
    assert name == "file://" + DATABASE + "?mode=ro"
    assert secret == ""


@pytest.fixture
def volumes(tmp_path, monkeypatch):
    source = ROOT / "deploy/local/prepare_volumes.py"
    spec = importlib.util.spec_from_file_location("database_folder_prepare", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for name in ("state", "provider-keys", "secrets", "host-secrets"):
        (tmp_path / name).mkdir(mode=0o755)
    for name in ("first-admin-password", "gateway-runtime-key", "gateway-admin-key"):
        (tmp_path / "host-secrets" / name).write_text("synthetic-private-credential")
    monkeypatch.setattr(module, "Path", lambda value: tmp_path / value.lstrip("/"))
    monkeypatch.setattr(module.os, "chown", lambda *args: None)
    module.state = tmp_path / "state"
    return module


def database(path, rows):
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE approvals (model_id TEXT)")
    connection.executemany("INSERT INTO approvals VALUES (?)", [(row,) for row in rows])
    connection.commit()
    connection.close()


def approvals(path):
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return [row for (row,) in connection.execute("SELECT model_id FROM approvals")]
    finally:
        connection.close()


def test_edm04_a_new_preview_gets_a_private_database_folder(volumes):
    volumes.prepare()
    folder = volumes.state / "database"
    assert folder.is_dir() and stat.S_IMODE(folder.stat().st_mode) == 0o700
    assert list(folder.iterdir()) == []
    assert (volumes.state / "django-secret-key").is_file()
    volumes.prepare()
    assert list(folder.iterdir()) == []


def test_edm05_an_earlier_database_moves_into_the_folder(volumes):
    old, new = volumes.state / "keeplane.sqlite3", volumes.state / "database/keeplane.sqlite3"
    database(old, ["demo"])
    volumes.prepare()
    # First start: the same file under both names, so an app still running
    # from before writes the database the new app reads.
    assert os.path.samefile(old, new) and approvals(new) == ["demo"]
    volumes.prepare()
    assert not old.exists() and approvals(new) == ["demo"]
    volumes.prepare()
    assert approvals(new) == ["demo"]
    # An empty file an earlier app created under the old name is removed.
    old.touch()
    volumes.prepare()
    assert not old.exists() and approvals(new) == ["demo"]


@pytest.mark.parametrize("case", ["-journal", "-wal", "two databases"])
def test_edm06_an_unclear_earlier_database_stops_start_up_unchanged(volumes, case):
    old, new = volumes.state / "keeplane.sqlite3", volumes.state / "database/keeplane.sqlite3"
    database(old, ["earlier"])
    if case == "two databases":
        new.parent.mkdir(mode=0o700)
        database(new, ["later"])
    else:
        old.with_name(old.name + case).write_bytes(b"synthetic journal")
    before = old.read_bytes()
    with pytest.raises(RuntimeError):
        volumes.prepare()
    assert old.read_bytes() == before
    if case == "two databases":
        assert approvals(new) == ["later"] and not os.path.samefile(old, new)
    else:
        assert not new.exists()
