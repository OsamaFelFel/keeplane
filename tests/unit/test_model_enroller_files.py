"""The model enroller's init step in Kubernetes and its status-role setting.

Cases EF-01 to EF-07 in model-enroller-files-cases.md.
"""

import os
from pathlib import Path
import stat
import subprocess
import sys

import pytest
from prepare_enroller_files import Unprepared, plan, prepare

ROOT = Path(__file__).resolve().parents[2]
CONTROL_PLANE = ROOT / "components/control-plane"
ADMIN_KEY = "a" * 64
RUNTIME_KEY = "b" * 64
CA = "-----BEGIN CERTIFICATE-----\nMIIBsynthetic\n-----END CERTIFICATE-----"
ROLES = "keeplane_status_0,keeplane_status_1,keeplane_status_2"


def settings(pod="keeplane-gateway-1", **changes):
    environ = {
        "KEEPLANE_GATEWAY_COPY": pod,
        "KEEPLANE_ENROLLER_COPY_PREFIX": "keeplane-gateway-",
        "KEEPLANE_ENROLLER_STATUS_ROLES": ROLES,
        "KEEPLANE_ENROLLER_APPROVALS_PASSWORD": "approvals-password",
        "KEEPLANE_ENROLLER_STATUS_PASSWORD_0": "status-password-0",
        "KEEPLANE_ENROLLER_STATUS_PASSWORD_1": "status-password-1",
        "KEEPLANE_ENROLLER_STATUS_PASSWORD_2": "status-password-2",
        "KEEPLANE_ENROLLER_DATABASE_CA": CA,
        "KEEPLANE_ENROLLER_GATEWAY_ADMIN_KEY": ADMIN_KEY,
        "KEEPLANE_ENROLLER_GATEWAY_RUNTIME_KEY": RUNTIME_KEY,
    }
    environ.update(changes)
    return {name: value for name, value in environ.items() if value is not None}


def mode(path):
    return stat.S_IMODE(path.lstat().st_mode)


def test_ef_01_each_copy_gets_only_its_own_status_role_and_password(tmp_path):
    for index in range(3):
        files, guard = tmp_path / f"files-{index}", tmp_path / f"guard-{index}"
        role = prepare(settings(f"keeplane-gateway-{index}"), files, guard)
        assert role == f"keeplane_status_{index}"
        written = {path.name: path.read_text() for path in files.iterdir()}
        assert written["status-user"] == f"keeplane_status_{index}\n"
        assert written["status-password"] == f"status-password-{index}\n"
        # No other copy's status password reaches this copy's enroller.
        others = {f"status-password-{other}" for other in range(3)} - {
            f"status-password-{index}"
        }
        assert not any(other in value for other in others for value in written.values())


def test_ef_02_the_files_are_private_and_hold_only_what_the_enroller_needs(tmp_path):
    files, guard = tmp_path / "files", tmp_path / "guard"
    prepare(settings(), files, guard)
    assert sorted(path.name for path in files.iterdir()) == [
        "approvals-password", "database-ca.crt", "gateway-admin-key",
        "gateway-runtime-key", "signing-secret", "status-password", "status-user",
    ]
    assert mode(files) == 0o700
    assert all(mode(path) == 0o400 for path in files.iterdir())
    assert all(path.lstat().st_uid == os.geteuid() for path in files.iterdir())
    assert (files / "approvals-password").read_text() == "approvals-password\n"
    assert (files / "gateway-admin-key").read_text() == ADMIN_KEY + "\n"
    assert (files / "gateway-runtime-key").read_text() == RUNTIME_KEY + "\n"
    assert (files / "database-ca.crt").read_text() == CA + "\n"
    # The guard folder is made private and left empty for the enroller.
    assert mode(guard) == 0o700 and list(guard.iterdir()) == []


def test_ef_03_the_signing_secret_is_random_and_never_the_apps(tmp_path):
    first = plan(settings())["signing-secret"]
    second = plan(settings())["signing-secret"]
    assert first != second
    # Long enough for the app's settings check (48 characters at least).
    assert len(first) >= 48


def test_ef_04_a_restarted_init_step_replaces_its_own_files(tmp_path):
    files, guard = tmp_path / "files", tmp_path / "guard"
    prepare(settings(), files, guard)
    before = (files / "signing-secret").read_text()
    prepare(settings(KEEPLANE_ENROLLER_STATUS_PASSWORD_1="rotated"), files, guard)
    assert (files / "status-password").read_text() == "rotated\n"
    assert (files / "signing-secret").read_text() != before
    assert not [path for path in files.iterdir() if path.name.startswith(".enroller-")]


@pytest.mark.parametrize("pod", [
    "keeplane-gateway-3", "keeplane-gateway-01", "keeplane-gateway-", "keeplane-app-1",
    "other-gateway-1", "keeplane-gateway-1-extra", "",
])
def test_ef_05_a_pod_that_is_not_a_listed_copy_is_refused(tmp_path, pod):
    with pytest.raises(Unprepared, match="not one of the gateway copies"):
        prepare(settings(pod), tmp_path / "files", tmp_path / "guard")
    assert not (tmp_path / "files").exists()


@pytest.mark.parametrize(("changes", "message"), [
    ({"KEEPLANE_ENROLLER_STATUS_ROLES": ""}, "lowercase status role"),
    ({"KEEPLANE_ENROLLER_STATUS_ROLES": "Keeplane_Status,b,c"}, "lowercase status role"),
    ({"KEEPLANE_ENROLLER_STATUS_ROLES": "a;drop,b,c"}, "lowercase status role"),
    ({"KEEPLANE_ENROLLER_STATUS_ROLES": "a,a,c"}, "its own status role"),
    ({"KEEPLANE_ENROLLER_STATUS_PASSWORD_1": None}, "STATUS_PASSWORD_1 is missing"),
    ({"KEEPLANE_ENROLLER_STATUS_PASSWORD_1": "  "}, "STATUS_PASSWORD_1 is missing"),
    ({"KEEPLANE_ENROLLER_APPROVALS_PASSWORD": None}, "APPROVALS_PASSWORD is missing"),
    ({"KEEPLANE_ENROLLER_APPROVALS_PASSWORD": "status-password-1"}, "different passwords"),
    ({"KEEPLANE_ENROLLER_GATEWAY_ADMIN_KEY": "short"}, "not a valid gateway key"),
    ({"KEEPLANE_ENROLLER_GATEWAY_RUNTIME_KEY": "b" * 31 + "!"}, "not a valid gateway key"),
    ({"KEEPLANE_ENROLLER_DATABASE_CA": "not a certificate"}, "not a PEM certificate"),
    ({"KEEPLANE_ENROLLER_DATABASE_CA": None}, "DATABASE_CA is missing"),
])
def test_ef_06_missing_or_unsafe_settings_write_nothing(tmp_path, changes, message):
    with pytest.raises(Unprepared, match=message) as refused:
        prepare(settings(**changes), tmp_path / "files", tmp_path / "guard")
    assert not (tmp_path / "files").exists() and not (tmp_path / "guard").exists()
    # A refusal never repeats a secret value.
    for value in settings().values():
        if "password" in value or value in (ADMIN_KEY, RUNTIME_KEY):
            assert value not in str(refused.value)


def test_ef_06_a_guard_path_that_is_not_a_folder_is_refused(tmp_path):
    (tmp_path / "target").mkdir()
    (tmp_path / "guard").symlink_to(tmp_path / "target")
    with pytest.raises(Unprepared, match="not a private folder"):
        prepare(settings(), tmp_path / "files", tmp_path / "guard")


def settings_probe(tmp_path, **environ):
    """Load the real settings in a fresh process and report the status role."""
    (tmp_path / "password").write_text("approvals\n")
    (tmp_path / "status-password").write_text("status\n")
    (tmp_path / "signing").write_text("s" * 64)
    base = {
        "PATH": os.environ.get("PATH", ""),
        "DJANGO_SECRET_KEY_FILE": str(tmp_path / "signing"),
        "KEEPLANE_DATABASE_HOST": "postgres.example.test",
        "KEEPLANE_DATABASE_NAME": "keeplane",
        "KEEPLANE_DATABASE_USER": "keeplane_enroller",
        "KEEPLANE_DATABASE_PASSWORD_FILE": str(tmp_path / "password"),
        "KEEPLANE_DATABASE_READ_ONLY": "1",
        "KEEPLANE_GUARD_STATUS_DATABASE_PASSWORD_FILE": str(tmp_path / "status-password"),
    }
    probe = (
        "import json; from config import settings as s; "
        "d = s.DATABASES.get('guard_status'); "
        "print(json.dumps(d and [d['USER'], d['PASSWORD'], d['OPTIONS']['options']]))"
    )
    return subprocess.run(
        [sys.executable, "-c", probe], cwd=CONTROL_PLANE, env={**base, **environ},
        capture_output=True, text=True, timeout=60,
    )


def test_ef_07_the_status_role_can_come_from_the_copys_file(tmp_path):
    (tmp_path / "status-user").write_text("keeplane_status_1\n")
    result = settings_probe(
        tmp_path, KEEPLANE_GUARD_STATUS_DATABASE_USER_FILE=str(tmp_path / "status-user"))
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == (
        '["keeplane_status_1", "status", "-c default_transaction_read_only=on"]')
    # The setting form keeps working, as the guard-status guide describes.
    result = settings_probe(tmp_path, KEEPLANE_GUARD_STATUS_DATABASE_USER="keeplane_status_0")
    assert result.returncode == 0, result.stderr
    assert '"keeplane_status_0"' in result.stdout


def test_ef_07_an_empty_or_doubly_named_status_role_stops_start_up(tmp_path):
    (tmp_path / "empty").write_text("\n")
    (tmp_path / "status-user").write_text("keeplane_status_1\n")
    empty = settings_probe(tmp_path, KEEPLANE_GUARD_STATUS_DATABASE_USER_FILE=str(tmp_path / "empty"))
    assert empty.returncode != 0 and "The guard status role file is empty" in empty.stderr
    both = settings_probe(
        tmp_path, KEEPLANE_GUARD_STATUS_DATABASE_USER="keeplane_status_0",
        KEEPLANE_GUARD_STATUS_DATABASE_USER_FILE=str(tmp_path / "status-user"))
    assert both.returncode != 0 and "Name the guard status role once" in both.stderr
    missing = settings_probe(
        tmp_path, KEEPLANE_GUARD_STATUS_DATABASE_USER_FILE=str(tmp_path / "absent"))
    assert missing.returncode != 0
