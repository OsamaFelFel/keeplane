"""Replay the transient model-store read failure observed in the kind trial."""

import importlib.util
import json
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("preview_server", ROOT / "components/control-plane/server.py")
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)


def run_case(sequence):
    calls = []

    def gateway(path, timeout):
        calls.append((path, timeout))
        return sequence[len(calls) - 1]

    with patch.object(server, "gateway", side_effect=gateway), patch.object(server.time, "sleep"):
        status, result = server.gateway_model_resources()
    return status, result, calls


def main():
    recovered = run_case([(500, {"error": "timeout"}), (200, {"resources": []})])
    timed_out = run_case([(503, {"error": "Gateway unavailable"}), (200, {"resources": []})])
    persistent = run_case([(500, {"error": "timeout"})] * 3)
    results = [
        {"case": "MGMT-01", "verdict": "pass" if recovered[0] == 200 and len(recovered[2]) == 2
         and all(path == "/api/config/resources/llm.model" and timeout == 10
                 for path, timeout in recovered[2]) else "fail",
         "observed": {"status": recovered[0], "read_attempts": len(recovered[2])}},
        {"case": "MGMT-02", "verdict": "pass" if persistent[0] == 500 and len(persistent[2]) == 3 else "fail",
         "observed": {"status": persistent[0], "read_attempts": len(persistent[2])}},
        {"case": "MGMT-03", "verdict": "pass" if timed_out[0] == 200 and len(timed_out[2]) == 2
         and all(timeout == 10 for _, timeout in timed_out[2]) else "fail",
         "observed": {"status": timed_out[0], "read_attempts": len(timed_out[2]),
                      "timeout_seconds": 10}},
    ]
    print(json.dumps({"suite": "Keeplane gateway management read retry", "results": results}, indent=2))
    return 1 if any(result["verdict"] == "fail" for result in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
