"""Fresh operator enrollment and current policy protect both private stages."""

import json
from copy import deepcopy

import pytest
from data_classes.models import ProjectClass
from django.test import override_settings
from integrations.gateway.applied import applied_fingerprint
from model_registry import installed_runtime, runtime_callback
from model_registry.fingerprints import fingerprint
from model_registry.installed_runtime import digest
from model_registry.models import ModelApproval
from model_registry.provider_keys import managed_key_digest

from tests.unit.test_applied_gateway import dump

pytest_plugins = ("tests.integration.test_runtime_callback",)


@pytest.fixture
def installed(callback, tmp_path, monkeypatch):
    f = callback
    for row in f.resources:
        row["value"] = {
            "id": row["id"],
            "name": row["id"],
            "provider": "openAI",
            "params": {
                "model": "upstream-" + row["id"],
                "baseUrl": "https://provider.invalid/v1",
            },
        }
        ModelApproval.objects.filter(pk=row["id"]).update(
            gateway_fingerprint=fingerprint(row["id"], f.resources)
        )
    f.file = {"config": {}, "gateways": {}, "binds": [], "policies": []}
    f.requests = []
    f.applied = {
        "workloads": [],
        "services": [],
        "binds": [],
        "routes": {},
        "policies": [],
        "backends": [],
        "models": [],
        "version": {},
        "config": {},
    }
    monkeypatch.setattr(
        installed_runtime, "read_applied", lambda gateway: deepcopy(f.applied)
    )

    def request(path, *, timeout, connection_retries):
        assert timeout == 5 and connection_retries == 0
        f.requests.append(path)
        return f.state.status, deepcopy(
            {
                "/api/config": f.file,
                "/api/config/effective": f.effective,
                "/api/config/resources/llm.model": {"resources": f.resources},
            }[path]
        )

    f.gateway.request = request
    monkeypatch.setattr(runtime_callback, "MODEL_GATEWAY", f.gateway)
    f.manifest_file = tmp_path / "enrollment.json"
    f.key_directory = tmp_path / "keys"
    f.key_directory.mkdir(mode=0o700)
    monkeypatch.setenv("PROVIDER_KEY_DIR", str(f.key_directory))
    f.write = lambda: f.manifest_file.write_text(json.dumps(f.declaration))

    def enroll(choice="none", key_name="", key_digest=""):
        f.effective = dict(
            deepcopy(f.file),
            llm={"models": [deepcopy(r["value"]) for r in f.resources]},
        )
        fp = fingerprint("private", f.resources)
        ModelApproval.objects.filter(pk="private").update(
            gateway_fingerprint=fp, key_choice=choice
        )
        f.declaration = {
            "version": 2,
            "enabled": True,
            "file_digest": digest(f.file),
            "effective_digest": digest(f.effective),
            "applied_digest": applied_fingerprint(f.applied),
            "models": {
                "private": {
                    "fingerprint": fp,
                    "key_choice": choice,
                    "key_name": key_name,
                    "key_digest": key_digest,
                }
            },
        }
        f.write()
        return fp

    f.enroll = enroll
    f.fp = enroll()
    f.manifest_file.chmod(0o600)
    with override_settings(RUNTIME_GUARD_MANIFEST_FILE=str(f.manifest_file)):
        yield f


def send(f, selected=False, **changes):
    body = {"project_id": f.project, "model_id": "private"}
    if selected:
        body["definition_fingerprint"] = f.fp
    body.update(changes)
    return f.client.post(
        "/internal/runtime/installed/" + ("selected" if selected else "entry"),
        data=json.dumps(body),
        content_type="application/json",
        HTTP_AUTHORIZATION="Bearer " + f.token,
        HTTP_X_KEEPLANE_GATEWAY_CREDENTIAL=f.key,
        HTTP_X_KEEPLANE_DEFINITION_FINGERPRINT="forged-client-claim",
    )


@pytest.mark.parametrize("selected", [False, True])
def test_both_stages_return_only_canonical_metadata_and_leave_resources_unchanged(
    installed, selected
):
    before = deepcopy(installed.resources)
    response = send(installed, selected)
    assert response.status_code == 200
    assert response.json() == {
        "actor_id": installed.actor["id"],
        "project_id": installed.project,
        "model_id": "private",
    }
    assert "no-store" in response["Cache-Control"]
    assert installed.resources == before
    assert all(
        value not in response.content.decode()
        for value in (installed.token, installed.key, installed.fp)
    )


@pytest.mark.parametrize(
    "change",
    [
        "missing",
        "disabled",
        "malformed",
        "duplicate",
        "oversized",
        "writable",
        "symlink",
        "relative",
        "version",
        "extra",
        "unknown-key-choice",
    ],
)
def test_invalid_manifest_refuses_before_gateway_reads(installed, change):
    f = installed
    if change == "missing":
        f.manifest_file.unlink()
    elif change == "disabled":
        f.declaration["enabled"] = False
        f.write()
    elif change in ("malformed", "duplicate", "oversized"):
        f.manifest_file.write_text(
            {
                "malformed": "[" * 2000,
                "duplicate": '{"enabled":true,"enabled":false}',
                "oversized": "x" * 65537,
            }[change]
        )
    elif change == "writable":
        f.manifest_file.chmod(0o666)
    elif change == "symlink":
        other = f.manifest_file.with_suffix(".other")
        f.manifest_file.rename(other)
        f.manifest_file.symlink_to(other)
    elif change == "relative":
        with override_settings(RUNTIME_GUARD_MANIFEST_FILE="enrollment.json"):
            assert send(f).status_code == 503
        assert not f.requests
        return
    else:
        if change == "unknown-key-choice":
            f.declaration["models"]["private"]["key_choice"] = "unknown"
        else:
            f.declaration[change] = 1 if change == "version" else True
        f.write()
    assert send(f).status_code == 503
    assert not f.requests


@pytest.mark.parametrize(
    "model", ["public", "outside", "local-fixture", "virtual", "private*"]
)
def test_uninstalled_aliases_are_denied_even_if_approved(installed, model):
    assert send(installed, model_id=model).status_code == 403
    assert not installed.requests


@pytest.mark.parametrize(
    "change",
    [
        "revision",
        "definition",
        "approval",
        "personal",
        "file",
        "effective",
        "outage",
        "boolean-revision",
    ],
)
def test_fresh_definition_approval_key_choice_and_complete_wiring_are_required(
    installed, change
):
    f = installed
    if change in ("revision", "boolean-revision"):
        f.resources[0]["revision"] = 2 if change == "revision" else True
    elif change == "definition":
        f.resources[0]["value"]["params"]["baseUrl"] = "https://changed.invalid/v1"
    elif change == "approval":
        ModelApproval.objects.filter(pk="private").delete()
    elif change == "personal":
        ModelApproval.objects.filter(pk="private").update(key_choice="personal")
    elif change in ("file", "effective"):
        getattr(f, change)["policies"] = [{"changed": True}]
    else:
        f.state.status = 503
    response = send(f, True)
    assert response.status_code == 503
    assert response.json() == {"error": "Gateway authorization is unavailable"}


def test_new_enrollment_still_refuses_old_selected_overlay(installed):
    installed.resources[0]["revision"] += 1
    new_fp = installed.enroll()
    assert send(installed).status_code == 200
    assert send(installed, True).status_code == 503
    assert send(installed, True, definition_fingerprint=new_fp).status_code == 200


@pytest.mark.parametrize("selected", [False, True])
@pytest.mark.parametrize("fault", ["changed", "missing", "outage"])
def test_both_stages_require_fresh_complete_applied_state(
    installed, monkeypatch, selected, fault
):
    if fault == "changed":
        installed.applied["policies"].append({"unexpected": True})
    elif fault == "missing":
        installed.applied = {}
    else:
        from integrations.gateway.applied import AppliedStateUnavailable

        def unavailable(gateway):
            raise AppliedStateUnavailable()

        monkeypatch.setattr(installed_runtime, "read_applied", unavailable)
    assert send(installed, selected).status_code == 503


def test_name_only_resource_cannot_be_enrolled_with_an_indexed_native_target(installed):
    del installed.resources[0]["value"]["id"]
    installed.enroll()
    assert send(installed).status_code == 503


@pytest.mark.parametrize(
    "change",
    [
        "headers",
        "inline-key",
        "provider-credentials",
        "wildcard",
        "url-tab",
        "url-newline",
    ],
)
def test_trusted_fingerprint_does_not_admit_unsupported_shapes(installed, change):
    value = installed.resources[0]["value"]
    if change == "headers":
        value["requestHeaders"] = {"set": {"authorization": "untrusted"}}
    elif change == "inline-key":
        value["auth"] = {"key": {"value": "untrusted"}}
    elif change == "provider-credentials":
        value["params"]["baseUrl"] = "https://user:secret@provider.invalid/v1"
    elif change in ("url-tab", "url-newline"):
        value["params"]["baseUrl"] = (
            "https://provider.invalid/" + ("\t" if change == "url-tab" else "\n") + "v1"
        )
    else:
        value["name"] = "private*"
    installed.enroll()
    assert send(installed).status_code == 503


@pytest.mark.parametrize("auth", [False, 0, "", []])
def test_keyless_falsy_malformed_auth_is_not_a_supported_empty_value(installed, auth):
    installed.resources[0]["value"]["auth"] = auth
    installed.enroll()
    assert send(installed).status_code == 503


@pytest.mark.parametrize("auth", [None, {}])
def test_keyless_explicit_null_or_empty_object_remains_supported(installed, auth):
    installed.resources[0]["value"]["auth"] = auth
    installed.enroll()
    assert send(installed).status_code == 200


@pytest.mark.parametrize(
    "change",
    ["missing", "replacement", "invalid", "unreadable", "link", "resource-name"],
)
def test_shared_key_is_bound_to_immutable_name_and_content(installed, change):
    path = installed.key_directory / ("key-" + "a" * 32)
    path.write_text("synthetic-managed-provider-key")
    installed.resources[0]["value"]["auth"] = {"key": {"value": {"file": str(path)}}}
    installed.fp = installed.enroll(
        "shared", path.name, managed_key_digest(str(installed.key_directory), str(path))
    )
    assert send(installed, True).status_code == 200
    if change == "missing":
        path.unlink()
    elif change == "replacement":
        path.write_text("another-valid-provider-key")
    elif change == "invalid":
        path.write_text("invalid-provider-key\n")
    elif change == "unreadable":
        path.chmod(0)
    elif change == "link":
        target = path.with_suffix(".other")
        path.rename(target)
        path.symlink_to(target)
    else:
        installed.resources[0]["value"]["auth"]["key"]["value"]["file"] = str(
            path.with_name("key-" + "b" * 32)
        )
    assert send(installed, True).status_code == 503


@pytest.mark.parametrize("fault", ["json", "incomplete", "nonfinite"])
def test_malformed_management_replies_fail_without_reflecting_them(installed, fault):
    request = installed.gateway.request

    def malformed(path, **kwargs):
        if path == "/api/config":
            if fault == "json":
                raise ValueError("synthetic-private-diagnostic")
            if fault == "incomplete":
                return 200, {"synthetic-private-diagnostic": True}
            return 200, dict(installed.file, unexpected=float("nan"))
        return request(path, **kwargs)

    installed.gateway.request = malformed
    response = send(installed)
    assert response.status_code == 503
    assert "synthetic-private-diagnostic" not in response.content.decode()


def test_current_actor_and_project_class_remain_required(installed):
    assert send(installed).status_code == 200
    ProjectClass.objects.filter(pk=installed.project).update(data_class_id="public")
    assert send(installed).status_code == 403
    installed.stores.identity.logout(installed.token)
    installed.requests.clear()
    assert send(installed).status_code == 401
    assert not installed.requests


def test_selected_metadata_is_exact_and_ignores_client_fingerprint_header(installed):
    assert send(installed, True, definition_fingerprint="invalid").status_code == 400
    assert send(installed, True, prompt="untrusted-content").status_code == 400
    assert send(installed, definition_fingerprint=installed.fp).status_code == 400
    assert not installed.requests


def test_existing_gateway_installation_is_not_enabled_by_a_manifest(
    installed, monkeypatch
):
    monkeypatch.setenv("GATEWAY_MODE", "existing")
    assert send(installed).status_code == 503
    assert not installed.requests


@pytest.fixture
def health_snapshot(installed):
    f = installed
    f.applied = dump()
    f.group = f.applied["backends"][0]["backend"]["ai"]["target"]["providers"][0]
    f.group["active"]["private"] = f.group["active"].pop("model")
    f.info = f.group["active"]["private"]["info"]
    f.applied["policies"] = [{"extAuthz": {"failureMode": "deny"}}]
    f.enroll()
    return f


@pytest.mark.parametrize("selected", [False, True])
def test_failure_and_recovery_measurements_do_not_require_manifest_rewrite(
    health_snapshot, selected
):
    f = health_snapshot
    original = f.manifest_file.read_bytes()
    f.info.update(health=0.7, consecutiveFailures=1, totalRequests=1)
    assert send(f, selected).status_code == 200
    f.info.update(
        health=0.79, consecutiveFailures=0, requestLatency=0.02, totalRequests=2
    )
    assert send(f, selected).status_code == 200
    assert f.manifest_file.read_bytes() == original


@pytest.mark.parametrize("selected", [False, True])
@pytest.mark.parametrize(
    "change",
    [
        "membership",
        "timesEjected",
        "evictedUntil",
        "capacity",
        "target",
        "guard",
        "auth",
        "unknown",
        "bad-health",
        "bad-count",
        "missing-health",
    ],
)
def test_health_normalization_does_not_hide_wiring_eviction_or_malformed_state(
    health_snapshot, selected, change
):
    f = health_snapshot
    endpoint = f.group["active"]["private"]
    f.info.update(health=0.7, consecutiveFailures=1)
    if change == "membership":
        f.group["rejected"]["private"] = f.group["active"].pop("private")
    elif change in ("timesEjected", "evictedUntil"):
        f.info[change] = 1
    elif change == "capacity":
        endpoint["capacity"] = 2
    elif change == "target":
        endpoint["endpoint"]["hostOverride"] = "changed.invalid:443"
    elif change == "guard":
        f.applied["policies"][0]["extAuthz"]["failureMode"] = "allow"
    elif change == "auth":
        f.applied["backends"][0]["inlinePolicies"] = [{"backendAuth": {}}]
    elif change == "bad-health":
        f.info["health"] = float("nan")
    elif change == "bad-count":
        f.info["consecutiveFailures"] = True
    elif change == "missing-health":
        del f.info["health"]
    else:
        f.info["unknown"] = True
    assert send(f, selected).status_code == 503


@pytest.mark.parametrize("selected", [False, True])
def test_current_class_and_approval_still_withdraw_during_health_drift(
    health_snapshot, selected
):
    f = health_snapshot
    f.info.update(health=0.7, consecutiveFailures=1)
    ProjectClass.objects.filter(pk=f.project).update(data_class_id="public")
    assert send(f, selected).status_code == 403
    ModelApproval.objects.filter(pk="private").delete()
    assert send(f, selected).status_code == 503


def test_shared_key_withdrawal_still_denies_during_health_drift(health_snapshot):
    f = health_snapshot
    path = f.key_directory / ("key-" + "a" * 32)
    path.write_text("synthetic-managed-provider-key")
    f.resources[0]["value"]["auth"] = {"key": {"value": {"file": str(path)}}}
    f.fp = f.enroll(
        "shared", path.name, managed_key_digest(str(f.key_directory), str(path))
    )
    f.info.update(health=0.7, consecutiveFailures=1)
    assert send(f, True).status_code == 200
    path.unlink()
    assert send(f, True).status_code == 503


def test_old_signature_denies_until_explicit_reenrollment(health_snapshot):
    f = health_snapshot
    old_dump = deepcopy(f.applied)
    info = old_dump["backends"][0]["backend"]["ai"]["target"]["providers"][0]["active"][
        "private"
    ]["info"]
    for field in ("requestLatency", "pendingRequests", "totalRequests"):
        del info[field]
    f.declaration["applied_digest"] = digest(old_dump)
    f.write()
    assert send(f).status_code == 503
    f.enroll()
    assert send(f).status_code == 200
