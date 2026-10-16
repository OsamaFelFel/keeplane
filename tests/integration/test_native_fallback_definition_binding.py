"""Check each fallback candidate's own controlled definition generation."""

import json

import pytest

from tests.integration.test_native_definition_binding import HEADER
from tests.integration.test_native_runtime_fallback import fallback_config
from tests.support.native_runtime_trial import native_runtime_trial


def config(existing, admin):
    value = fallback_config(existing, admin)
    value["frontendPolicies"] = {"accessLog": {"database": {"llm": "metadata"}}}
    for route in value["binds"][0]["listeners"][0]["routes"]:
        route["policies"]["retry"]["backoff"] = "500ms"
        http = route["policies"]["extAuthz"]["protocol"]["http"]
        http["path"] = '"/fixture/definition-entry"'
        http["includeResponseHeaders"] = [HEADER]
        http["addRequestHeaders"]["x-fixture-requested-alias"] = (
            "json(request.body).model"
        )
    for policy in value["policies"]:
        auth = policy["policy"]["extAuthz"]
        http = auth["protocol"]["http"]
        http["path"] = '"/fixture/definition-selected"'
        http["includeResponseHeaders"] = ["authorization"]
        auth["includeRequestHeaders"].append(HEADER)
    return value


@pytest.mark.live
@pytest.mark.infrastructure
@pytest.mark.parametrize("existing", [False, True], ids=["managed", "existing"])
def test_native_fallback_uses_each_bound_generation(tmp_path, report_file, existing):
    report = {"existing": existing, "passed": False, "requests": []}

    def save():
        report_file.write_text(json.dumps(report, indent=2) + "\n")

    save()
    with native_runtime_trial(
        tmp_path,
        existing,
        config,
        fallback=True,
        actor_keys=True,
        definition_binding=True,
        definition_fallback=True,
    ) as trial:
        report["versions"] = trial.call("fallback_binding_versions")
        save()
        assert report["versions"]["private_current_on_both"]
        assert report["versions"]["same_endpoint"]
        assert (
            report["versions"]["current_revision"]
            > report["versions"]["stale_revision"]
        )

        def probe(
            label,
            port,
            status,
            contacts,
            callbacks,
            markers,
            known_map=False,
            requested="fallback",
        ):
            trial.call("reset")
            trial.call("binding_reset")
            result = trial.probe(
                {
                    "port": port,
                    "body": {
                        "model": requested,
                        "messages": [{"role": "user", "content": "synthetic fallback"}],
                    },
                    "headers": {
                        HEADER: trial.call("fallback_binding_map")
                        if known_map
                        else json.dumps(
                            {
                                "private": trial.generation_a,
                                "public": trial.generation_a,
                            }
                        ),
                        "X-API-Key": "client-provider-forgery",
                        "X-Fixture-Requested-Alias": "fallback",
                        "X-Keeplane-Actor-ID": trial.call("actor_id", "b"),
                    },
                    "observe_credentials": True,
                }
            )
            observed = trial.call("summary")
            binding = trial.call("binding_summary")
            report["requests"].append(
                {
                    "case": label,
                    "status": result["status"],
                    "contacts": observed["calls"],
                    "key_callbacks": binding["key_callbacks"],
                    "checks": binding["checks"],
                    "server_key_used": observed["provider_key_used"],
                    "developer_forwarded": observed["developer_key_forwarded"],
                    "context_headers": observed["credential_headers"],
                    "generation_forwarded": observed["generation_forwarded"],
                    "forged_headers": observed["forged_headers"],
                    "authorization_returned": result["authorization_returned"],
                }
            )
            save()
            assert result["status"] == status
            assert observed["calls"] == contacts
            assert binding["key_callbacks"] == callbacks
            assert binding["checks"][0]["marker_models"] == markers
            assert [
                (row["stage"], row["model"], row["status"]) for row in binding["checks"]
            ] == [("entry", "private", 403 if requested != "fallback" else 200)] + [
                ("selected", model, 200) for model in callbacks
            ]
            assert [row["model_id"] for row in observed["decisions"]] == [
                "private"
            ] + callbacks
            assert all(
                row["keys"] == ["model_id", "project_id"]
                for row in observed["decisions"]
            )
            assert observed["provider_key_used"] == [True] * len(contacts)
            assert observed["developer_key_forwarded"] == [False] * len(contacts)
            assert observed["generation_forwarded"] == [False] * len(contacts)
            assert observed["forged_headers"] == [False] * len(contacts)
            assert observed["credential_headers"] == [
                {
                    "Authorization": True,
                    "X-Keeplane-Gateway-Credential": False,
                    "X-Keeplane-Project-ID": False,
                }
            ] * len(contacts)
            assert not result["authorization_returned"]

        probe("unrelated-model", 5000, 403, [], [], [], requested="customer-owned")
        probe(
            "current",
            5000,
            200,
            ["mock-generation-b", "mock-public-current"],
            ["private", "public"],
            ["private", "public"],
        )
        probe(
            "stale-public",
            5001,
            403,
            ["mock-generation-b"],
            ["private"],
            ["private", "public"],
        )
        for fault in ("missing", "malformed", "oversized"):
            trial.call("fallback_binding_fault", fault)
            probe(fault, 5000, 403, [], [], ["private", "public"], known_map=True)
        trial.call("fallback_binding_fault", "")
        probe(
            "recovered-map",
            5000,
            200,
            ["mock-public-current"],
            ["public"],
            ["private", "public"],
        )
        assert trial.call("binding_reject_reuse") is True
        assert trial.call("fallback_binding_reject_reuse") is True
        trial.call("withdraw_public")
        probe("withdrawn-approval", 5000, 403, [], [], ["private"], known_map=True)
        trial.call("fallback_binding_restore")
        trial.call("fallback_binding_outside")
        probe(
            "outside-public-edit",
            5000,
            403,
            ["mock-generation-b"],
            ["private"],
            ["private"],
            known_map=True,
        )
        assert trial.call("config") == trial.before
        assert trial.before["existing_preserved"]
        assert trial.before["existing_listed"] is existing
    report["passed"] = True
    save()
