"""Each gateway copy's confirmed guard, recorded and checked per copy (ADR 027).

Cases GS-01 to GS-26 in guard-status-cases.md. These run on SQLite with the
fake gateway of test_model_enroller and the HTTP checks of
test_installed_runtime. The PostgreSQL roles and row-level security are in
test_guard_status_postgres.py.
"""

import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from common import credential_check
from common.errors import StorageUnavailable
from django.core.management.base import CommandError
from django.db import DatabaseError
from django.test import override_settings
from django.utils import timezone
from integrations.gateway.runtime_config import (
    RuntimeInstallationUnavailable,
    callback_copies,
)
from model_registry import (
    guard_status,
    installed_runtime,
    model_choice,
    model_enroller,
    personal_transport,
    runtime_callback,
    runtime_installation,
)
from model_registry.fingerprints import fingerprint
from model_registry.guard_status import GuardStatusRecorder
from model_registry.management.commands import run_model_enroller
from model_registry.models import GatewayGuardStatus, ModelApproval
from model_registry.provider_keys import managed_key_digest

from tests.integration.test_installed_personal_runtime import handoff
from tests.integration.test_installed_runtime import send
from tests.integration.test_model_choice import ask, chosen
from tests.integration.test_model_enroller import approve, declaration, held, model

pytest_plugins = (
    "tests.integration.test_model_choice",
    "tests.integration.test_model_enroller",
)
COPY = "keeplane-gateway-0"
OTHER = "keeplane-gateway-1"


def row(name=COPY):
    found = GatewayGuardStatus.objects.filter(pk=name).values().first()
    return None if found is None else found


# --- The enroller records its own copy's confirmed guard ----------------


class Recorder(GuardStatusRecorder):
    """The real recorder on the test database, counting its writes."""

    def __init__(self, name=COPY):
        super().__init__(name, using="default")
        self.writes, self.fail = [], False

    def _write(self, confirmed, value):
        if self.fail:
            raise DatabaseError("synthetic status outage")
        self.writes.append(confirmed)
        super()._write(confirmed, value)


def copy_enroller(f, name=COPY, recorder=None):
    installation = runtime_installation.DjangoRuntimeInstallation(
        f.gateway,
        f.directory,
        f.directory / "trusted.json",
        str(f.directory),
        read_applied=f.enroller.installation.read_applied,
        gateway_copy=name,
    )
    f.status = recorder or Recorder(name)
    return model_enroller.DjangoModelEnroller(
        installation,
        deadline=0.5,
        sleep=lambda seconds: None,
        now=lambda: f.clock,
        status=f.status,
    )


@pytest.fixture
def copy(gateway):
    gateway.enroller = copy_enroller(gateway)
    return gateway


def test_gs_01_a_confirmed_guard_is_recorded_with_its_models_and_time(copy):
    f = copy
    before = timezone.now()
    assert f.enroller.reconcile() == model_enroller.Enrolment("enrolled", ("demo",))
    found = row()
    assert found["confirmed"] is True and found["confirmed_at"] >= before
    assert found["declaration"] == declaration(f)
    assert found["declaration"]["models"]["demo"]["fingerprint"] == fingerprint(
        "demo", f.resources
    )
    # Cleared before the guard moved, confirmed only after it read back.
    assert f.status.writes == [False, True]


def test_gs_02_an_unchanged_guard_writes_nothing_again(copy):
    f = copy
    f.enroller.reconcile()
    f.status.writes.clear()
    assert f.enroller.reconcile().state == "unchanged"
    assert f.status.writes == []


def test_gs_03_the_first_pass_after_the_operator_enrolment_records_it(copy):
    f = copy
    f.enroller.reconcile()
    GatewayGuardStatus.objects.all().delete()  # as after the operator's enrolment
    f.status.writes.clear()
    assert f.enroller.reconcile().state == "unchanged"
    assert f.status.writes == [True]
    assert row()["declaration"] == declaration(f)


def test_gs_04_nothing_is_confirmed_while_the_guard_moves(copy):
    f = copy
    f.enroller.reconcile()
    f.resources.append(model("second"))
    approve("second", f.resources)
    seen = []
    f.during = lambda: seen.append(row()["confirmed"])
    assert f.enroller.reconcile().models == ("demo", "second")
    assert seen == [False]
    assert set(row()["declaration"]["models"]) == {"demo", "second"}


def test_gs_05_a_guard_that_never_reads_back_leaves_nothing_confirmed(
    copy, monkeypatch
):
    f = copy
    f.enroller.reconcile()
    f.resources.append(model("second"))
    approve("second", f.resources)
    f.apply = False
    ticks = iter([0, 16])
    monkeypatch.setattr(
        runtime_installation,
        "time",
        SimpleNamespace(monotonic=lambda: next(ticks), sleep=lambda seconds: None),
    )
    with pytest.raises(RuntimeInstallationUnavailable):
        f.enroller.reconcile()
    assert row()["confirmed"] is False and row()["declaration"] is None
    assert row()["confirmed_at"] is None


def test_gs_06_a_failed_pass_that_changed_nothing_keeps_the_confirmation(
    copy, monkeypatch
):
    f = copy
    f.enroller.reconcile()
    before = row()
    guard = (f.directory / "gateway.json").read_bytes(), declaration(f)
    f.status.writes.clear()

    def unreadable(path):
        raise RuntimeInstallationUnavailable("synthetic")

    monkeypatch.setattr(f.enroller, "_read", unreadable)
    with pytest.raises(RuntimeInstallationUnavailable):
        f.enroller.reconcile()
    # ADR 027 "Failure": the guard wasn't touched, so its confirmation stands.
    assert ((f.directory / "gateway.json").read_bytes(), declaration(f)) == guard
    assert row() == before and f.status.writes == []


def test_gs_07_if_the_row_cannot_be_written_the_guard_is_not_touched(copy):
    f = copy
    f.enroller.reconcile()
    f.resources.append(model("second"))
    approve("second", f.resources)
    guard = (f.directory / "gateway.json").read_bytes(), declaration(f)
    f.status.fail = True
    with pytest.raises(StorageUnavailable):
        f.enroller.reconcile()
    assert ((f.directory / "gateway.json").read_bytes(), declaration(f)) == guard
    # The next pass, with the database back, enrols as usual.
    f.status.fail = False
    assert f.enroller.reconcile().models == ("demo", "second")
    assert row()["confirmed"] is True


def test_gs_08_a_held_change_keeps_the_old_confirmed_guard(copy):
    f = copy
    f.enroller.reconcile()
    old = row()
    f.resources[0] = model("demo", revision=2, base_url="https://new.example")
    approve("demo", f.resources)
    held(f)
    assert row() == old
    f.enroller.reconcile()
    assert row()["declaration"]["models"]["demo"]["fingerprint"] == fingerprint(
        "demo", f.resources
    )


def test_gs_09_withdrawing_every_model_records_nothing_confirmed(copy):
    f = copy
    f.enroller.reconcile()
    ModelApproval.objects.filter(pk="demo").delete()
    f.resources.clear()
    held(f)
    assert f.enroller.reconcile().state == "withdrawn"
    assert row()["confirmed"] is False


def test_gs_10_the_guard_names_this_copy_and_is_replaced_if_it_does_not(gateway):
    f = gateway
    # A guard enrolled without a copy name (as in the Docker preview).
    f.enroller.reconcile()
    assert callback_copies(f.file()) == {None}
    f.enroller = copy_enroller(f)
    assert f.enroller.reconcile().state == "enrolled"
    assert callback_copies(f.file()) == {COPY}
    assert f.enroller.reconcile().state == "unchanged"


def test_gs_11_the_docker_preview_keeps_no_row(gateway):
    gateway.enroller.reconcile()
    assert callback_copies(gateway.file()) == {None}
    assert not GatewayGuardStatus.objects.exists()


def test_gs_12_one_copy_never_records_for_another(gateway):
    installation = runtime_installation.DjangoRuntimeInstallation(
        gateway.gateway,
        gateway.directory,
        gateway.directory / "trusted.json",
        str(gateway.directory),
        gateway_copy=COPY,
    )
    for status in (None, Recorder(OTHER)):
        with pytest.raises(TypeError):
            model_enroller.DjangoModelEnroller(installation, status=status)


@pytest.mark.parametrize(
    "environment",
    [
        {"KEEPLANE_GATEWAY_COPY": COPY},
        {"databases": True},
        {"KEEPLANE_GATEWAY_COPY": COPY, "databases": True},
        {"KEEPLANE_GATEWAY_COPY": "Not_A_Pod", "databases": True},
    ],
)
def test_gs_13_the_enroller_refuses_a_partial_or_preview_status_setup(
    settings, monkeypatch, environment
):
    environment = dict(environment)
    databases = {"default": dict(settings.DATABASES["default"])}
    if environment.pop("databases", False):
        databases["guard_status"] = dict(databases["default"])
    monkeypatch.delenv("KEEPLANE_GATEWAY_COPY", raising=False)
    for key, value in environment.items():
        monkeypatch.setenv(key, value)
    # SQLite here: the status write needs PostgreSQL and a separate role.
    with pytest.raises(CommandError):
        run_model_enroller.guard_status_recorder(databases)


def test_gs_13_postgresql_needs_a_read_only_approvals_role_and_its_own_status_role(
    monkeypatch,
):
    monkeypatch.setenv("KEEPLANE_GATEWAY_COPY", COPY)
    read_only = {"options": "-c default_transaction_read_only=on"}
    default = {"ENGINE": "common.postgresql", "USER": "enroller", "OPTIONS": read_only}
    status = {"ENGINE": "common.postgresql", "USER": "status0", "OPTIONS": read_only}
    for changed in (
        {"default": {**default, "OPTIONS": {}}, "guard_status": status},
        {"default": default, "guard_status": {**status, "USER": "enroller"}},
    ):
        with pytest.raises(CommandError):
            run_model_enroller.guard_status_recorder(changed)
    name, recorder = run_model_enroller.guard_status_recorder(
        {"default": default, "guard_status": status}
    )
    assert name == COPY and recorder.using == "guard_status"


def test_gs_13_the_docker_preview_needs_no_status_setup(monkeypatch):
    monkeypatch.delenv("KEEPLANE_GATEWAY_COPY", raising=False)
    assert run_model_enroller.guard_status_recorder() == (None, None)


# --- The app checks the sending copy's row -------------------------------


def copy_url(name):
    return f"http://{name}.keeplane-gateway-copies.team.svc:4000"


@pytest.fixture
def per_copy(installed, monkeypatch, tmp_path):
    f = installed
    reads = []
    applied_from = []

    def copy_gateway(name):
        def request(path, *, timeout, connection_retries):
            reads.append((name, path))
            return f.gateway.request(
                path, timeout=timeout, connection_retries=connection_retries
            )

        return SimpleNamespace(base_url=copy_url(name), request=request)

    listed = SimpleNamespace(
        copies=[copy_gateway(COPY), copy_gateway(OTHER)], misconfigured=False
    )
    for module in (runtime_callback, personal_transport, model_choice):
        monkeypatch.setattr(module, "MODEL_GATEWAY_COPIES", listed)

    def applied(gateway):
        applied_from.append(gateway.base_url)
        return deepcopy(f.applied)

    monkeypatch.setattr(installed_runtime, "read_applied", applied)
    f.listed, f.copy_reads, f.applied_from = listed, reads, applied_from

    def confirm(name=COPY, value=None, confirmed=True):
        now = timezone.now()
        GatewayGuardStatus.objects.update_or_create(
            copy_name=name,
            defaults={
                "confirmed": confirmed,
                "declaration": deepcopy(f.declaration if value is None else value)
                if confirmed
                else None,
                "confirmed_at": now if confirmed else None,
                "updated_at": now,
            },
        )

    f.confirm = confirm
    confirm(COPY)
    # The app cannot read a copy's private file in Kubernetes.
    f.manifest_file.unlink()
    with override_settings(GUARD_STATUS_CHECK=True):
        yield f


def check(f, selected=False, copy_name=COPY, **changes):
    if copy_name is not None:
        changes["gateway_copy"] = copy_name
    return send(f, selected, **changes)


@pytest.mark.parametrize("selected", [False, True])
def test_gs_14_a_check_from_a_confirmed_copy_is_allowed(per_copy, selected):
    f = per_copy
    response = check(f, selected)
    assert response.status_code == 200
    assert response.json()["model_id"] == "private"
    # Every gateway read went to the sending copy, none to the shared address.
    assert f.requests and all(name == COPY for name, _ in f.copy_reads)
    assert f.applied_from == [copy_url(COPY)]


@pytest.mark.parametrize("selected", [False, True])
@pytest.mark.parametrize("state", ["missing", "unconfirmed", "malformed", "other-copy"])
def test_gs_15_a_copy_without_a_confirmed_row_is_refused(per_copy, selected, state):
    f = per_copy
    GatewayGuardStatus.objects.all().delete()
    if state == "unconfirmed":
        f.confirm(confirmed=False)
    elif state == "malformed":
        broken = deepcopy(f.declaration)
        broken["models"]["private"]["fingerprint"] = "not-a-fingerprint"
        f.confirm(value=broken)
    elif state == "other-copy":
        # Another copy's confirmation never vouches for this one.
        f.confirm(OTHER)
    response = check(f, selected)
    assert response.status_code == 503
    assert response.json() == {"error": "Gateway authorization is unavailable"}
    assert not f.copy_reads


def test_gs_16_a_model_the_copy_has_not_confirmed_is_refused(per_copy):
    f = per_copy
    assert check(f, model_id="public").status_code == 403
    assert check(f, True, model_id="public").status_code == 403


def test_gs_17_a_stale_row_is_refused(per_copy):
    f = per_copy
    old = f.fp
    # The admin moves the model on; the copy's row still lists the old guard.
    f.resources[0]["revision"] += 1
    new = fingerprint("private", f.resources)
    ModelApproval.objects.filter(pk="private").update(gateway_fingerprint=new)
    for supplied in (old, new):
        assert check(f, True, definition_fingerprint=supplied).status_code == 503
    # The row names the old fingerprint until that copy's enroller confirms.
    f.enroll()
    f.confirm()
    assert check(f, True, definition_fingerprint=old).status_code == 503
    assert check(f, True, definition_fingerprint=new).status_code == 200


@pytest.mark.parametrize("fault", ["applied", "file", "unreadable"])
def test_gs_18_a_row_that_no_longer_matches_its_copy_is_refused(per_copy, fault):
    f = per_copy
    if fault == "applied":
        f.applied["policies"].append({"unexpected": True})
    elif fault == "file":
        f.file["policies"] = [{"changed": True}]
    else:
        f.state.status = 503
    assert check(f, True).status_code == 503


@pytest.mark.parametrize(
    "name, status",
    [(None, 400), ("Keeplane_0", 400), ("keeplane-gateway-7", 503)],
)
def test_gs_19_a_check_that_names_no_known_copy_is_refused(per_copy, name, status):
    f = per_copy
    f.confirm("keeplane-gateway-7")
    assert check(f, True, copy_name=name).status_code == status
    assert not f.copy_reads


def test_gs_19_an_unusable_copy_list_refuses_every_check(per_copy):
    per_copy.listed.misconfigured = True
    assert check(per_copy, True).status_code == 503


def test_gs_20_an_unreadable_status_table_refuses(per_copy, monkeypatch):
    def unavailable(*args, **kwargs):
        raise DatabaseError("synthetic")

    monkeypatch.setattr(GatewayGuardStatus.objects, "filter", unavailable)
    assert check(per_copy, True).status_code == 503


def test_gs_21_without_the_per_copy_check_a_named_copy_is_refused(installed):
    f = installed
    assert send(f, True).status_code == 200
    assert send(f, True, gateway_copy=COPY).status_code == 400
    assert not GatewayGuardStatus.objects.exists()


@pytest.fixture
def personal_copy(personal, per_copy):
    personal.confirm()
    return personal


def test_gs_22_a_personal_key_exchange_checks_the_sending_copy(personal_copy):
    f = personal_copy
    assert handoff(f).status_code == 400  # no copy named
    assert handoff(f, gateway_copy=OTHER).status_code == 503  # not confirmed
    response = handoff(f, gateway_copy=COPY)
    assert response.status_code == 200
    assert json.loads(response.content)["token_type"] == "Bearer"


@pytest.fixture
def choice_copy(choice, per_copy):
    return choice


def test_gs_23_model_choice_picks_only_models_every_copy_confirmed(choice_copy):
    f = choice_copy
    f.install("public")
    f.store.remove("private")
    # Only one copy confirmed the new model: it is not picked.
    f.confirm()
    older = {**f.declaration, "models": {"private": f.declaration["models"]["private"]}}
    f.confirm(OTHER, value=older)
    assert ask(f).json()["model_id"] is None
    f.confirm(OTHER)
    assert ask(f).json() == chosen(f, "public", "missing")
    assert not f.reads


def test_gs_23_model_choice_needs_every_listed_copy(choice_copy):
    f = choice_copy
    f.install("public")
    f.store.remove("private")
    f.confirm()
    assert ask(f).json()["model_id"] is None


@pytest.mark.parametrize("fault", ["none", "key-replaced", "definition-moved"])
def test_gs_25_model_choice_applies_the_live_definition_and_shared_key_checks(
    choice_copy, fault
):
    f = choice_copy
    path = f.key_directory / ("key-" + "e" * 32)
    path.write_text("synthetic-shared-provider-key")
    public = next(r for r in f.resources if r["id"] == "public")
    public["value"]["auth"] = {"key": {"value": {"file": str(path)}}}
    fp = fingerprint("public", f.resources)
    f.stores.catalog.approve("public", ["Confidential"], fp, key_choice="shared")
    f.declaration["models"]["public"] = {
        "fingerprint": fp,
        "key_choice": "shared",
        "key_name": path.name,
        "key_digest": managed_key_digest(str(f.key_directory), str(path)),
    }
    f.confirm()
    f.confirm(OTHER)
    f.store.remove("private")
    if fault == "key-replaced":
        path.write_text("another-shared-provider-key")
    elif fault == "definition-moved":
        # Every copy still lists the old guard, but the gateway moved on.
        public["value"]["params"]["model"] = "upstream-moved"
    expected = "public" if fault == "none" else None
    assert ask(f).json()["model_id"] == expected


def test_gs_24_the_recorder_validates_what_it_records(db):
    recorder = GuardStatusRecorder(COPY, using="default")
    with pytest.raises(Exception):  # noqa: B017 - any refusal; nothing written
        recorder.confirm({"version": 2, "enabled": True})
    assert not GatewayGuardStatus.objects.exists()
    with pytest.raises(ValueError):
        GuardStatusRecorder("Not A Pod")
    assert guard_status.valid_copy_name(COPY)


# --- check_credentials (002-02) ------------------------------------------


@pytest.mark.parametrize("check", [True, False])
def test_gs_26_check_credentials_reports_guard_status_not_in_use(db, check):
    # SQLite, or the per-copy check off: nothing to check, and nothing fails.
    copies = [SimpleNamespace(base_url=f"http://{COPY}.gateway:15000")]
    with override_settings(GUARD_STATUS_CHECK=check):
        assert credential_check.guard_status_report(copies) == ("not in use", [], [])


@pytest.mark.parametrize(
    ("problems", "warnings", "passed"),
    [([], [], True), ([], ["a warning"], True), (["a problem"], [], False)],
)
def test_gs_26_only_a_guard_status_problem_fails_check_credentials(
    problems, warnings, passed
):
    with patch.object(credential_check, "database_status", return_value="connected"), \
            patch.object(credential_check, "gateway_models", return_value=[]), \
            patch.object(credential_check, "approvals", return_value=[]), \
            patch.object(credential_check, "gateway_status", return_value=[]), \
            patch.object(credential_check, "guard_status_report",
                         return_value=({"copies": []}, problems, warnings)):
        report, result = credential_check.check(SimpleNamespace(base_url="x"), [])
    assert result is passed
    assert report["guard_status_problems"] == problems
    assert report["guard_status_warnings"] == warnings
