"""The Docker preview's model enroller sees only the app database folder.

Cases EDM-01 to EDM-08 in enroller-database-mount-cases.md. The Compose
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


def test_edm04_a_new_preview_gets_a_private_database_folder(volumes, capsys):
    volumes.prepare()
    folder = volumes.state / "database"
    assert folder.is_dir() and stat.S_IMODE(folder.stat().st_mode) == 0o700
    assert list(folder.iterdir()) == []
    assert (volumes.state / "django-secret-key").is_file()
    volumes.prepare()
    assert list(folder.iterdir()) == []
    assert "Notice:" not in capsys.readouterr().out


EARLIER = ("keeplane.sqlite3", "accounts.sqlite3", "model-approvals.sqlite3")
VOLUME = "keeplane-accounts-trial_model-approvals"
# Stop this preview (with the enroller), remove every container still holding the
# volume (the earlier keeplane-accounts-trial project's stopped ones too), then the
# volume: Docker refuses `docker volume rm` while any container, even a stopped
# one, uses it.
FULL_RESET = (
    ("docker compose -f compose.yaml -f deploy/local/runtime.yaml --profile runtime "
     "down --remove-orphans"),
    f"docker ps -aq --filter volume={VOLUME} | xargs -r docker rm -f",
    f"docker volume rm {VOLUME}",
)
GUIDES = ("docs/guide/local-preview.md", "docs/guide/guarded-runtime.md")


def in_order(text, steps):
    positions = [text.index(step) for step in steps]
    return positions == sorted(positions)


@pytest.mark.parametrize("present", [EARLIER[:1], EARLIER[1:], EARLIER])
def test_edm05_earlier_preview_files_are_left_unchanged_with_a_notice(
    volumes, capsys, present
):
    # ADR 014: no migration. The earlier files stay as they were, unused.
    before = {}
    for name in present:
        database(volumes.state / name, ["earlier"])
        path = volumes.state / name
        before[name] = (path.read_bytes(), path.stat().st_mtime_ns)
    volumes.prepare()
    volumes.prepare()
    for name in present:
        path = volumes.state / name
        assert (path.read_bytes(), path.stat().st_mtime_ns) == before[name], name
    assert list((volumes.state / "database").iterdir()) == []
    notice = volumes.earlier_database_notice(list(present))
    assert capsys.readouterr().out.splitlines() == [notice] * 2
    files = ", ".join("/state/" + name for name in present)
    # The agreed wording: it prints on every start, so it says nothing about
    # having just started the database fresh.
    assert notice.startswith(
        "Notice: this preview keeps its app database in /state/database. It doesn't "
        f"use or import the earlier preview files ({files}) and leaves them "
        "unchanged. To reset the preview fully, "
    )
    assert "started it fresh" not in notice and "left them" not in notice
    for name in EARLIER:
        assert (("/state/" + name) in notice) == (name in present), name
    for words in ("keeplane-accounts-trial preview's stopped ones",
                  *(f"'{step}'" for step in FULL_RESET)):
        assert words in notice, words
    assert in_order(notice, FULL_RESET)
    # Both guides give the same full reset, in the same order; the first step
    # also stops the enroller.
    for name in GUIDES:
        guide = (ROOT / name).read_text()
        block = guide[guide.index(FULL_RESET[0]):]
        block = block[:block.index("```")]
        assert [line for line in block.splitlines()[:3]] == list(FULL_RESET), name


def test_edm05_the_guides_no_longer_promise_imported_accounts():
    guide = (ROOT / "docs/guide/local-preview.md").read_text()
    architecture = (ROOT / "docs/architecture/local-preview.md").read_text()
    readme = (ROOT / "README.md").read_text()
    for text in (guide, architecture, readme):
        flat = " ".join(text.split())
        for stale in ("are imported into Django", "Existing accounts and models are kept",
                      "Their data is imported", "original database files are kept"):
            assert stale not in flat, stale
    flat = " ".join(guide.split())
    for words in ("starts a fresh database there with only the first admin",
                  "left unused and unchanged", "each start prints a notice"):
        assert words in flat, words


def test_edm08_the_launcher_removes_the_earlier_previews_containers(monkeypatch):
    spec = importlib.util.spec_from_file_location("local_up_retire", ROOT / "deploy/local/up.py")
    up = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(up)
    calls = []

    def listing(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="old-app-1\nold-init-1\n")

    monkeypatch.setattr(up.subprocess, "run", listing)
    monkeypatch.setattr(up, "run", lambda command, **kwargs: calls.append(command) or "")
    up.retire_old_preview()
    # Stopped containers count too: they still hold the shared account volume.
    assert calls == [
        ["docker", "ps", "--all", "--filter",
         "label=com.docker.compose.project=keeplane-accounts-trial", "--format", "{{.Names}}"],
        ["docker", "rm", "--force", "old-app-1", "old-init-1"],
    ]
    calls.clear()
    monkeypatch.setattr(up.subprocess, "run", lambda command, **kwargs: calls.append(command)
                        or subprocess.CompletedProcess(command, 0, stdout=""))
    up.retire_old_preview()
    assert len(calls) == 1 and calls[0][:3] == ["docker", "ps", "--all"]


def test_edm07_earlier_accounts_are_not_imported_into_the_fresh_database(
    rendered, tmp_path
):
    command = rendered["app-migrate"]["command"]
    assert command[:2] == ["sh", "-ec"] and "import_preview" not in command[2]
    state = tmp_path / "state"
    (state / "database").mkdir(parents=True)
    with sqlite3.connect(state / "accounts.sqlite3") as db:
        db.execute("CREATE TABLE users(id,username,password_hash,role)")
        db.execute("INSERT INTO users VALUES('u1','earlier-developer','x','admin')")
    with sqlite3.connect(state / "model-approvals.sqlite3") as db:
        db.execute("CREATE TABLE approved_models(model_id,key_choice)")
        db.execute("INSERT INTO approved_models VALUES('earlier-model','none')")
    before = {p.name: p.read_bytes() for p in state.glob("*.sqlite3")}
    password = tmp_path / "first-admin-password"
    password.write_text("synthetic-first-admin-password-123")
    secret = tmp_path / "secret"
    secret.write_text("s" * 64)
    path = state / "database/keeplane.sqlite3"
    environment = {
        key: value for key, value in os.environ.items()
        if not key.startswith(("KEEPLANE_", "DJANGO_"))
    }
    environment.update(
        DJANGO_SETTINGS_MODULE="config.settings",
        KEEPLANE_SQLITE_PATH=str(path),
        DJANGO_SECRET_KEY_FILE=str(secret),
        FIRST_ADMIN_PASSWORD_FILE=str(password),
        PYTHONDONTWRITEBYTECODE="1",
    )
    # The preview's own migration step, with this interpreter.
    script = command[2].replace("python manage.py", f"'{sys.executable}' manage.py")
    subprocess.run(["sh", "-ec", script], cwd=ROOT / "components/control-plane",
                   env=environment, capture_output=True, text=True, timeout=300,
                   check=True)
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as db:
        users = [row for (row,) in db.execute("SELECT username FROM accounts_user")]
        models = db.execute("SELECT count(*) FROM accounts_modelapproval").fetchone()
    assert users == ["first-admin"] and models == (0,)
    assert before == {p.name: p.read_bytes() for p in state.glob("*.sqlite3")}


def test_edm06_start_up_repeats_only_this_starts_notice(monkeypatch, tmp_path):
    spec = importlib.util.spec_from_file_location("local_up", ROOT / "deploy/local/up.py")
    up = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(up)
    monkeypatch.setattr(up, "RUNTIME", tmp_path)
    calls = []
    notice = "Notice: this preview keeps its app database in /state/database."

    def run(command, **kwargs):
        calls.append(command)
        return "\n".join(["chown done", notice, notice, "other output"])

    monkeypatch.setattr(up, "run", run)
    assert up.earlier_database_notices({}, "2026-11-02T00:00:00Z") == [notice]
    assert calls == [["docker", "compose", "--env-file", str(tmp_path / ".env"), "logs",
                      "--no-color", "--no-log-prefix", "--since", "2026-11-02T00:00:00Z",
                      "account-volume-init"]]
    monkeypatch.setattr(up, "run", lambda command, **kwargs: "chown done\n")
    assert up.earlier_database_notices({}, "2026-11-02T00:00:00Z") == []
