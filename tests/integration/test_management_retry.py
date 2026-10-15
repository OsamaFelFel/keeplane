"""Replay the transient model-store read failure observed in the kind trial."""

import json
from unittest.mock import patch


from integrations.gateway.adapter import AgentgatewayModelAdapter


def run_case(sequence):
    calls = []

    def gateway(path, timeout):
        calls.append((path, timeout))
        return sequence[len(calls) - 1]

    adapter = AgentgatewayModelAdapter("http://fixture:4000", "", "")
    with (
        patch.object(adapter, "request", side_effect=gateway),
        patch("integrations.gateway.adapter.time.sleep"),
    ):
        status, result = adapter.resources()
    return status, result, calls


def run_cases():
    recovered = run_case([(500, {"error": "timeout"}), (200, {"resources": []})])
    timed_out = run_case(
        [(503, {"error": "Gateway unavailable"}), (200, {"resources": []})]
    )
    persistent = run_case([(500, {"error": "timeout"})] * 3)
    results = [
        {
            "case": "MGMT-01",
            "verdict": "pass"
            if recovered[0] == 200
            and len(recovered[2]) == 2
            and all(
                path == "/api/config/resources/llm.model" and timeout == 10
                for path, timeout in recovered[2]
            )
            else "fail",
            "observed": {"status": recovered[0], "read_attempts": len(recovered[2])},
        },
        {
            "case": "MGMT-02",
            "verdict": "pass"
            if persistent[0] == 500 and len(persistent[2]) == 3
            else "fail",
            "observed": {"status": persistent[0], "read_attempts": len(persistent[2])},
        },
        {
            "case": "MGMT-03",
            "verdict": "pass"
            if timed_out[0] == 200
            and len(timed_out[2]) == 2
            and all(timeout == 10 for _, timeout in timed_out[2])
            else "fail",
            "observed": {
                "status": timed_out[0],
                "read_attempts": len(timed_out[2]),
                "timeout_seconds": 10,
            },
        },
    ]
    print(
        json.dumps(
            {"suite": "Keeplane gateway management read retry", "results": results},
            indent=2,
        )
    )
    return 1 if any(result["verdict"] == "fail" for result in results) else 0


if __name__ == "__main__":
    raise SystemExit(run_cases())


def test_management_retry(monkeypatch, report_file, request):
    arguments = [__file__]
    monkeypatch.setattr("sys.argv", arguments)
    assert run_cases() in (None, 0)
