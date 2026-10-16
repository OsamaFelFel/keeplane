"""Fresh operator enrollment and current policy protect both private stages."""

import json
from copy import deepcopy

import pytest
from data_classes.models import ProjectClass
from django.test import override_settings
from model_registry import runtime_callback
from model_registry.fingerprints import fingerprint
from model_registry.installed_runtime import digest
from model_registry.models import ModelApproval
from model_registry.provider_keys import managed_key_digest

pytest_plugins = ("tests.integration.test_runtime_callback",)


@pytest.fixture
def installed(callback, tmp_path, monkeypatch):
    f = callback
    for row in f.resources:
        row["value"] = {
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
            "version": 1,
            "enabled": True,
            "file_digest": digest(f.file),
            "effective_digest": digest(f.effective),
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
        "personal",
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
        if change == "personal":
            f.declaration["models"]["private"]["key_choice"] = "personal"
        else:
            f.declaration[change] = 2 if change == "version" else True
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
