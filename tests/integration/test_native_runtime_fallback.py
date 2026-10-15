"""Check authorization of each selected native priority-failover candidate."""

import json

import pytest

from tests.integration.test_native_runtime_authorization import (
    external_authorization,
    gateway_config,
)
from tests.support.native_runtime_trial import native_runtime_trial


def fallback_config(existing, admin):
    value = gateway_config(existing, admin)
    for route in value["binds"][0]["listeners"][0]["routes"]:
        # This fixed test alias starts with private; no product alias approval is implied.
        route["policies"]["extAuthz"] = external_authorization('"private"')
        route["policies"]["retry"] = {"attempts": 1, "codes": [503]}
    for name in ("private", "public"):
        value["policies"].append(
            {
                "name": {"name": "fallback-selected-" + name, "namespace": ""},
                "target": {
                    "backend": {
                        "backend": {
                            "name": "llm:virtual-model:fallback:0",
                            "namespace": "",
                            "section": name,
                        }
                    }
                },
                "policy": {"extAuthz": external_authorization(json.dumps(name))},
            }
        )
    return value


@pytest.mark.live
@pytest.mark.infrastructure
@pytest.mark.parametrize("existing", [False, True], ids=["managed", "existing"])
@pytest.mark.parametrize("case", ["allowed", "class", "approval", "key"])
def test_native_fallback_checks_each_selected_model(
    tmp_path, report_file, existing, case
):
    with native_runtime_trial(
        tmp_path, existing, fallback_config, fallback=True
    ) as trial:
        if case != "class":
            trial.call("allow_public")
        if case == "approval":
            trial.call("withdraw_public")
        elif case == "key":
            trial.public_key_file.unlink()
        status = trial.probe(
            {
                "body": {
                    "model": "fallback",
                    "messages": [
                        {"role": "user", "content": "synthetic fallback prompt"}
                    ],
                }
            }
        )
        observed = trial.call("summary")
        expected_calls = (
            ["mock-private", "mock-public"] if case == "allowed" else ["mock-private"]
        )
        assert status in (
            {200} if case == "allowed" else {403, 503} if case == "key" else {403}
        )
        assert observed["calls"] == expected_calls
        assert [row["model_id"] for row in observed["decisions"]] == [
            "private",
            "private",
            "public",
        ]
        assert all(
            row["keys"] == ["model_id", "project_id"] for row in observed["decisions"]
        )
        assert observed["provider_key_used"] == [True] * len(expected_calls)
        assert observed["developer_key_forwarded"] == [False] * len(expected_calls)
        assert observed["credential_headers"] == [
            {
                "Authorization": True,
                "X-Keeplane-Gateway-Credential": False,
                "X-Keeplane-Project-ID": False,
            }
        ] * len(expected_calls)
        assert trial.call("config") == trial.before
        assert (
            trial.before["existing_preserved"]
            and trial.before["existing_listed"] is existing
        )
        report_file.write_text(
            json.dumps(
                {
                    "existing": existing,
                    "case": case,
                    "status": status,
                    "selected_models": [
                        row["model_id"] for row in observed["decisions"]
                    ],
                    "provider_contacts": observed["calls"],
                    "server_key_only": True,
                },
                indent=2,
            )
            + "\n"
        )
