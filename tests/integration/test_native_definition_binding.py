"""Bind controlled native publications to fresh generations before key delivery."""

import json

import pytest

from tests.integration.test_native_actor_provider_keys import actor_key_config
from tests.support.native_runtime_trial import native_runtime_trial

HEADER = "x-keeplane-definition-generation"


def definition_config(existing, admin):
    config = actor_key_config(existing, admin)
    for route in config["binds"][0]["listeners"][0]["routes"]:
        http = route["policies"]["extAuthz"]["protocol"]["http"]
        http["path"] = '"/fixture/definition-entry"'
        http["includeResponseHeaders"] = [HEADER]
    for policy in config["policies"]:
        auth = policy["policy"]["extAuthz"]
        auth["protocol"]["http"]["path"] = '"/fixture/definition-selected"'
        auth["includeRequestHeaders"].append(HEADER)
    return config


@pytest.mark.live
@pytest.mark.infrastructure
@pytest.mark.parametrize("existing", [False, True], ids=["managed", "existing"])
def test_native_selected_generation_precedes_key_callback(
    tmp_path, report_file, existing
):
    report = {"existing": existing, "passed": False, "requests": []}

    def save():
        report_file.write_text(json.dumps(report, indent=2) + "\n")

    save()
    with native_runtime_trial(
        tmp_path, existing, definition_config, actor_keys=True, definition_binding=True
    ) as trial:
        report["versions"] = trial.call("binding_versions")
        save()
        assert (
            report["versions"]["same_model_id"] and report["versions"]["same_endpoint"]
        )
        assert report["versions"]["different_parameters"]
        assert (
            report["versions"]["current_revision"]
            > report["versions"]["stale_revision"]
        )

        def probe(port, expected, contacts, callbacks, entry_status=200):
            trial.call("reset")
            trial.call("binding_reset")
            result = trial.probe(
                {
                    "port": port,
                    "headers": {
                        HEADER: trial.generation_a,
                        "X-API-Key": "client-provider-forgery",
                        "X-Keeplane-Actor-ID": trial.call("actor_id", "b"),
                    },
                    "observe_credentials": True,
                }
            )
            observed = trial.call("summary")
            binding_observed = trial.call("binding_summary")
            key_calls = binding_observed["key_callbacks"]
            report["requests"].append(
                {
                    "serving_copy": "current-b" if port == 5000 else "stale-a",
                    "status": result["status"],
                    "provider_contacts": observed["calls"],
                    "key_callbacks": len(key_calls),
                    "binding_checks": binding_observed["checks"],
                    "selected_models": [
                        row["model_id"] for row in observed["decisions"]
                    ],
                    "provider_key_used": observed["provider_key_used"],
                    "developer_key_forwarded": observed["developer_key_forwarded"],
                    "context_headers": observed["credential_headers"],
                    "generation_forwarded": observed["generation_forwarded"],
                    "forged_headers": observed["forged_headers"],
                    "authorization_returned": result["authorization_returned"],
                }
            )
            save()
            assert result["status"] == expected
            assert not result["authorization_returned"]
            assert observed["calls"] == contacts
            assert len(key_calls) == callbacks
            checks = binding_observed["checks"]
            assert [(row["stage"], row["status"]) for row in checks] == [
                ("entry", entry_status)
            ] + [("selected", 200)] * callbacks
            assert checks[0]["generation_added"] is (entry_status == 200)
            assert checks[0]["generation_matches"] is False
            assert all(row["catalog_visible"] for row in checks)
            assert all(row["generation_matches"] for row in checks[1:])
            assert all(
                row["keys"] == ["model_id", "project_id"]
                for row in observed["decisions"]
            )
            assert observed["provider_key_used"] == [True] * len(contacts)
            assert observed["developer_key_forwarded"] == [False] * len(contacts)
            assert observed["forged_headers"] == [False] * len(contacts)
            assert observed["generation_forwarded"] == [False] * len(contacts)
            assert observed["credential_headers"] == [
                {
                    "Authorization": True,
                    "X-Keeplane-Gateway-Credential": False,
                    "X-Keeplane-Project-ID": False,
                }
            ] * len(contacts)

        probe(5000, 200, ["mock-generation-b"], 1)
        probe(5001, 403, [], 0)
        assert trial.call("binding_reject_reuse") is True
        trial.call("binding_outside_edit")
        probe(5000, 403, [], 0, entry_status=403)
        assert trial.call("config") == trial.before
        assert trial.before["existing_preserved"]
        assert trial.before["existing_listed"] is existing
        report["passed"] = True
        save()
