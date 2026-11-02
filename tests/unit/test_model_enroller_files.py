"""The model enroller's init step in Kubernetes and its status-role setting.

Cases EF-01 to EF-13 in model-enroller-files-cases.md.
"""

import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys

import pytest
from prepare_enroller_files import (
    MAX_BASE, Unprepared, plan, prepare, prepare_copy, runtime_plan,
)

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


# --- The protected runtime (EF-08 to EF-13) -----------------------------------------

CALLBACK = "c" * 64
ADMIN_HASH = "sha256:" + hashlib.sha256(ADMIN_KEY.encode()).hexdigest()
RUNTIME_HASH = "sha256:" + hashlib.sha256(RUNTIME_KEY.encode()).hexdigest()
DATABASE_URL = "postgresql://keeplane:${KEEPLANE_DB_PASSWORD}@gateway-db:5432/keeplane"


def base(admin=("${GATEWAY_ADMIN_KEY_HASH}",), runtime=("${GATEWAY_RUNTIME_KEY_HASH}",),
         **config):
    """A gateway configuration in the form the chart renders it (ME-12)."""
    return json.dumps({
        "config": {"adminAddr": "127.0.0.1:15000", "storage": {"mode": "hybrid"},
                   "database": {"url": DATABASE_URL}, **config},
        "gateways": {"default": {"port": 4000}},
        "ui": {"gateways": "default", "policies": {"apiKey": {
            "mode": "strict", "keys": [{"keyHash": value} for value in admin]}}},
        "llm": {"policies": {"apiKey": {
            "mode": "strict", "keys": [{"keyHash": value} for value in runtime]}},
            "models": []},
    })


def runtime_settings(**changes):
    return settings(**{
        "KEEPLANE_ENROLLER_CALLBACK_KEY": CALLBACK,
        "KEEPLANE_ENROLLER_GATEWAY_ADMIN_KEY_HASH": ADMIN_HASH,
        "KEEPLANE_ENROLLER_GATEWAY_RUNTIME_KEY_HASH": RUNTIME_HASH,
        "KEEPLANE_ENROLLER_RUNTIME_BASE": base(),
        **changes,
    })


def test_ef_08_a_fresh_copy_gets_a_disabled_guard_its_callback_key_and_trusted_base(
        tmp_path):
    files, guard = tmp_path / "files", tmp_path / "guard"
    assert prepare_copy(runtime_settings(), files, guard) == "keeplane_status_1"
    assert sorted(path.name for path in guard.iterdir()) == [
        "callback-key", "gateway.json", "manifest.json", "trusted.json"]
    assert json.loads((guard / "manifest.json").read_text()) == {
        "version": 2, "enabled": False}
    assert (guard / "callback-key").read_text() == CALLBACK
    trusted = (guard / "trusted.json").read_bytes()
    # Byte for byte the gateway's starting file, in the installer's canonical form.
    assert trusted == (guard / "gateway.json").read_bytes()
    value = json.loads(trusted)
    assert trusted == json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    assert value["ui"]["policies"]["apiKey"]["keys"] == [{"keyHash": ADMIN_HASH}]
    assert value["llm"]["policies"]["apiKey"]["keys"] == [{"keyHash": RUNTIME_HASH}]
    # Only the key hashes are written out: no other credential reaches the guard.
    assert value["config"]["database"]["url"] == DATABASE_URL
    assert mode(guard) == 0o700
    assert all(mode(path) == 0o600 for path in guard.iterdir())
    assert all(path.lstat().st_uid == os.geteuid() for path in guard.iterdir())
    # The enroller's own files are as before (EF-02), with no runtime file.
    assert len(list(files.iterdir())) == 7


def test_ef_09_a_restarted_pod_starts_its_guard_afresh(tmp_path):
    files, guard = tmp_path / "files", tmp_path / "guard"
    prepare_copy(runtime_settings(), files, guard)
    # What the enroller left from the Pod's earlier start.
    (guard / "manifest.json").write_text('{"version":2,"enabled":true,"models":{}}')
    (guard / "served.json").write_text('{"served":{"m":"f"},"pending":null}')
    (guard / "candidate.json").write_text("{}")
    (guard / "gateway.json").write_text('{"guarded":true}')
    (guard / ".installation.lock").write_text("")
    rotated = "d" * 64
    prepare_copy(runtime_settings(KEEPLANE_ENROLLER_CALLBACK_KEY=rotated), files, guard)
    assert json.loads((guard / "manifest.json").read_text())["enabled"] is False
    assert not (guard / "served.json").exists() and not (guard / "candidate.json").exists()
    assert (guard / "gateway.json").read_bytes() == (guard / "trusted.json").read_bytes()
    assert (guard / "callback-key").read_text() == rotated
    # The enroller's lock stays; no temporary file is left.
    assert (guard / ".installation.lock").exists()
    assert not [path for path in guard.iterdir() if path.name.startswith(".runtime-")]


def test_ef_10_a_key_rotation_writes_out_both_hashes_only_when_given(tmp_path):
    rotating = base(admin=("${GATEWAY_ADMIN_KEY_HASH}", "${GATEWAY_ADMIN_KEY_HASH_NEXT}"),
                    runtime=("${GATEWAY_RUNTIME_KEY_HASH}",
                             "${GATEWAY_RUNTIME_KEY_HASH_NEXT}"))
    next_admin, next_runtime = "sha256:" + "1" * 64, "sha256:" + "2" * 64
    files = runtime_plan(runtime_settings(
        KEEPLANE_ENROLLER_RUNTIME_BASE=rotating,
        KEEPLANE_ENROLLER_GATEWAY_ADMIN_KEY_HASH_NEXT=next_admin,
        KEEPLANE_ENROLLER_GATEWAY_RUNTIME_KEY_HASH_NEXT=next_runtime))
    value = json.loads(files["trusted.json"])
    assert value["ui"]["policies"]["apiKey"]["keys"] == [
        {"keyHash": ADMIN_HASH}, {"keyHash": next_admin}]
    assert value["llm"]["policies"]["apiKey"]["keys"] == [
        {"keyHash": RUNTIME_HASH}, {"keyHash": next_runtime}]
    with pytest.raises(Unprepared, match="names a key hash this copy was not given"):
        runtime_plan(runtime_settings(KEEPLANE_ENROLLER_RUNTIME_BASE=rotating))


@pytest.mark.parametrize(("changes", "message"), [
    ({"KEEPLANE_ENROLLER_CALLBACK_KEY": None}, "CALLBACK_KEY is missing"),
    ({"KEEPLANE_ENROLLER_CALLBACK_KEY": "short"}, "not a valid callback key"),
    ({"KEEPLANE_ENROLLER_CALLBACK_KEY": "c" * 40 + "!"}, "not a valid callback key"),
    ({"KEEPLANE_ENROLLER_GATEWAY_ADMIN_KEY_HASH": None}, "ADMIN_KEY_HASH is missing"),
    ({"KEEPLANE_ENROLLER_GATEWAY_RUNTIME_KEY_HASH": "sha256:XYZ"}, "not a sha256 key hash"),
    ({"KEEPLANE_ENROLLER_GATEWAY_ADMIN_KEY_HASH_NEXT": "plain"}, "not a sha256 key hash"),
    ({"KEEPLANE_ENROLLER_RUNTIME_BASE": None}, "RUNTIME_BASE is missing"),
    ({"KEEPLANE_ENROLLER_RUNTIME_BASE": "{not json"}, "RUNTIME_BASE is not JSON"),
    ({"KEEPLANE_ENROLLER_RUNTIME_BASE": "[]"}, "not a gateway configuration"),
    ({"KEEPLANE_ENROLLER_RUNTIME_BASE": base(adminAddr="0.0.0.0:15000")},
     "admin address must stay on loopback"),
    ({"KEEPLANE_ENROLLER_RUNTIME_BASE": base(admin=("${GATEWAY_ADMIN_KEY_HASH_NEXT}",))},
     "names a key hash this copy was not given"),
    ({"KEEPLANE_ENROLLER_STATUS_PASSWORD_1": None}, "STATUS_PASSWORD_1 is missing"),
])
def test_ef_11_a_missing_or_unsafe_runtime_setting_writes_nothing(tmp_path, changes,
                                                                   message):
    files, guard = tmp_path / "files", tmp_path / "guard"
    with pytest.raises(Unprepared, match=message) as refused:
        prepare_copy(runtime_settings(**changes), files, guard)
    assert not files.exists() and not guard.exists()
    for value in (CALLBACK, ADMIN_KEY, RUNTIME_KEY):
        assert value not in str(refused.value)


def padded(size, fill="x"):
    """A base of exactly size bytes, padded in a setting the step leaves alone."""
    empty = len(base(note="").encode())
    return base(note=fill * ((size - empty) // len(fill.encode())))


def test_ef_12_a_base_over_the_one_value_limit_is_refused_clearly(tmp_path):
    # Linux starts no process with one environment value over 128 KiB; the
    # chart and this step stop at 120 KiB, so the message names the cause.
    assert MAX_BASE == 122880
    at_limit = padded(MAX_BASE)
    assert len(at_limit.encode()) == MAX_BASE
    assert runtime_plan(runtime_settings(KEEPLANE_ENROLLER_RUNTIME_BASE=at_limit))
    # One byte over; and under the limit in characters but over it in bytes.
    wide = base(note="wide").replace('"wide"', '"' + "é" * (MAX_BASE // 2) + '"')
    assert len(wide) <= MAX_BASE < len(wide.encode())
    for over in (padded(MAX_BASE + 1), wide):
        files, guard = tmp_path / "files", tmp_path / "guard"
        with pytest.raises(Unprepared, match=r"RUNTIME_BASE is over 122880 bytes \(120 KiB\)"):
            prepare_copy(runtime_settings(KEEPLANE_ENROLLER_RUNTIME_BASE=over), files, guard)
        assert not files.exists() and not guard.exists()


def test_ef_13_only_the_key_hash_variables_must_be_given(tmp_path):
    # A gateway database password variable named GATEWAY_* is the gateway's
    # to read from its own environment: it is left as it is, not refused.
    url = "postgresql://keeplane:${GATEWAY_DB_PASSWORD}@gateway-db:5432/keeplane"
    configuration = json.loads(base())
    configuration["config"]["database"]["url"] = url
    configuration["config"]["note"] = "${GATEWAY_REGION}"
    files, guard = tmp_path / "files", tmp_path / "guard"
    prepare_copy(runtime_settings(KEEPLANE_ENROLLER_RUNTIME_BASE=json.dumps(configuration)),
                 files, guard)
    value = json.loads((guard / "trusted.json").read_text())
    assert value["config"]["database"]["url"] == url
    assert value["config"]["note"] == "${GATEWAY_REGION}"
    assert value["ui"]["policies"]["apiKey"]["keys"] == [{"keyHash": ADMIN_HASH}]
    # Each known key-hash variable still has to be given when the base names it.
    for name in ("GATEWAY_ADMIN_KEY_HASH", "GATEWAY_RUNTIME_KEY_HASH"):
        with pytest.raises(Unprepared, match=f"{name} is missing"):
            runtime_plan(runtime_settings(**{f"KEEPLANE_ENROLLER_{name}": None}))
    for name in ("GATEWAY_ADMIN_KEY_HASH_NEXT", "GATEWAY_RUNTIME_KEY_HASH_NEXT"):
        named = base(admin=("${GATEWAY_ADMIN_KEY_HASH}", "${" + name + "}"))
        with pytest.raises(Unprepared, match="names a key hash this copy was not given"):
            runtime_plan(runtime_settings(KEEPLANE_ENROLLER_RUNTIME_BASE=named))
