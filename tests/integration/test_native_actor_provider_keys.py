"""Prove trusted, per-request synthetic actor-key delivery without production wiring."""

import json

import pytest

from tests.integration.test_native_runtime_authorization import gateway_config
from tests.support.native_runtime_trial import native_runtime_trial


def actor_key_config(existing, admin):
    config = gateway_config(existing, admin)
    config["frontendPolicies"] = {"accessLog": {"database": {"llm": "metadata"}}}
    for policy in config["policies"]:
        http = policy["policy"]["extAuthz"]["protocol"]["http"]
        http["path"] = '"/fixture/actor-key-authorize"'
        http["includeResponseHeaders"] = ["authorization"]
    return config


@pytest.mark.live
@pytest.mark.infrastructure
@pytest.mark.parametrize("existing", [False, True], ids=["managed", "existing"])
def test_native_authorizer_selects_each_actors_provider_key(
    tmp_path, report_file, existing
):
    report = {"existing": existing, "passed": False, "requests": []}

    def save():
        report_file.write_text(json.dumps(report, indent=2) + "\n")

    save()
    with native_runtime_trial(
        tmp_path, existing, actor_key_config, actor_keys=True
    ) as trial:

        def request(actor, expected_status, expected_provider=None, forged_auth=False):
            trial.select_actor(actor)
            trial.call("reset")
            headers = {
                "X-API-Key": "client-provider-forgery",
                "X-Provider-Authorization": "Bearer client-provider-forgery",
                "X-Keeplane-Actor-ID": trial.call(
                    "actor_id", "b" if actor == "a" else "a"
                ),
            }
            if forged_auth:
                headers["Authorization"] = "Bearer client-provider-forgery"
            result = trial.probe({"headers": headers, "observe_credentials": True})
            status = result["status"]
            observed = trial.call("summary")
            report["requests"].append(
                {
                    "actor": actor,
                    "status": status,
                    "provider_actors": observed["provider_actor"],
                    "provider_contacts": observed["calls"],
                    "selected_models": [
                        row["model_id"] for row in observed["decisions"]
                    ],
                    "provider_key_used": observed["provider_key_used"],
                    "developer_key_forwarded": observed["developer_key_forwarded"],
                    "forged_headers": observed["forged_headers"],
                    "credential_headers": observed["credential_headers"],
                    "authorization_returned": result["authorization_returned"],
                }
            )
            save()
            assert status == expected_status
            assert [row["model_id"] for row in observed["decisions"]] == ["private"] * (
                1 if forged_auth else 2
            )
            assert all(
                row["keys"] == ["model_id", "project_id"]
                for row in observed["decisions"]
            )
            count = int(expected_provider is not None)
            assert observed["calls"] == ["mock-private"] * count
            assert observed["provider_actor"] == ([expected_provider] if count else [])
            assert observed["provider_key_used"] == [True] * count
            assert observed["developer_key_forwarded"] == [False] * count
            assert observed["forged_headers"] == [False] * count
            assert (
                observed["credential_headers"]
                == [
                    {
                        "Authorization": True,
                        "X-Keeplane-Gateway-Credential": False,
                        "X-Keeplane-Project-ID": False,
                    }
                ]
                * count
            )
            assert not result["authorization_returned"]

        request("a", 200, "a")
        request("b", 403)  # B has never added a provider key.
        trial.call("actor_key_replace", "b")
        request("b", 200, "b")
        request("a", 200, "a")  # Switching actors cannot reuse B's key.
        trial.call("actor_key_remove", "a")
        request("a", 403)  # Withdrawal is fresh before provider dispatch.
        request("b", 200, "b")
        trial.call("actor_key_replace", "a")
        request("a", 200, "a")
        trial.call("actor_key_replace", "a")
        request("a", 200, "a")  # A valid replacement is used on the next request.
        request("a", 401, forged_auth=True)
        assert trial.call("config") == trial.before
        report["passed"] = True
        save()
