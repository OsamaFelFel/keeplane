"""Exercise bounded read retries without contacting or changing a gateway."""

from collections import Counter
import json
from unittest.mock import patch

import gateway_preflight as preflight


RUNTIME = (200, {"build": {"version": "1.6.0"}})
MODELS = (200, {"data": []})
MANAGEMENT = (200, {"resources": []})


def scenario(model_reads, management_reads):
    replies = {
        "/api/runtime": [RUNTIME],
        "/v1/models": list(model_reads),
        "/api/config/resources/llm.model": list(management_reads),
    }
    calls = []

    def respond(path, body=None):
        calls.append((path, body))
        return replies[path].pop(0)

    with patch.object(preflight, "URL", "http://fixture"), \
            patch.object(preflight, "EXPECTED_VERSION", "1.6.0"), \
            patch.object(preflight, "MODEL", ""), \
            patch.object(preflight, "fetch", side_effect=respond), \
            patch.object(preflight.time, "sleep") as sleep:
        passed, message = preflight.check()
    counts = Counter(path for path, _ in calls)
    return passed, message, counts, all(body is None for _, body in calls), sleep.call_count


def record(identifier, passed, observed):
    return {"case": identifier, "verdict": "pass" if passed else "fail", "observed": observed}


def main():
    results = []
    passed, message, calls, read_only, waits = scenario([(0, None), MODELS], [(0, None), MANAGEMENT])
    results.append(record("K8S-14", passed and read_only and waits == 2 and
                          calls["/v1/models"] == 2 and calls["/api/config/resources/llm.model"] == 2,
                          {"message": message, "model_reads": calls["/v1/models"],
                           "management_reads": calls["/api/config/resources/llm.model"]}))

    passed, message, calls, read_only, waits = scenario([MODELS], [(503, None), (503, None)])
    results.append(record("K8S-15", not passed and read_only and waits == 1 and
                          calls["/api/config/resources/llm.model"] == 2 and
                          message == "Gateway model-management read API is unavailable",
                          {"message": message, "management_reads": calls["/api/config/resources/llm.model"]}))

    passed, message, calls, read_only, waits = scenario([MODELS], [(401, None)])
    results.append(record("K8S-16", not passed and read_only and waits == 0 and
                          calls["/api/config/resources/llm.model"] == 1 and
                          message == "Gateway model-management read API is unavailable",
                          {"message": message, "management_reads": calls["/api/config/resources/llm.model"]}))

    print(json.dumps({"results": results}, indent=2))
    return int(any(row["verdict"] == "fail" for row in results))


if __name__ == "__main__":
    raise SystemExit(main())
