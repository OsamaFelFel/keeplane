"""Spec 004 ST16: the gateway retries a model that is down, then stops.

Owner decision of 31 October 2026: the same model is retried twice on a 5xx,
a timeout or a 429 that arrives before the first streamed byte. A stream that
has started is never retried, and the model is never switched.
"""

import json

import pytest
from integrations.gateway.runtime_config import RETRY_ATTEMPTS, outage_retry

from tests.integration.test_native_runtime_authorization import gateway_config
from tests.support.native_runtime_trial import native_runtime_trial

# The product waits 60 seconds per attempt; the fixture uses 2 seconds so a
# timeout case finishes quickly. Every other value is the product's own.
FIXTURE_ATTEMPT_TIMEOUT = "2s"


def outage_config(existing, admin, *, timeout=None):
    value = gateway_config(existing, admin)
    for route in value["binds"][0]["listeners"][0]["routes"]:
        route["policies"].update(outage_retry())
        if timeout:
            route["policies"]["timeout"] = {"backendRequestTimeout": timeout}
    return value


def fixture_config(existing, admin):
    return outage_config(existing, admin, timeout=FIXTURE_ATTEMPT_TIMEOUT)


ALL_DOWN = ["503"] * (RETRY_ATTEMPTS + 1)

CASES = {
    # case: (provider script, stream, expected status, expected provider contacts)
    "down-503": (ALL_DOWN, False, {503}, RETRY_ATTEMPTS + 1),
    "down-500": (["500"] * 3, False, {500}, 3),
    "down-502": (["502"] * 3, False, {502}, 3),
    "down-504": (["504"] * 3, False, {504}, 3),
    "rate-limited": (["429"] * 3, False, {429}, 3),
    "recovers-on-second-retry": (["503", "503", "ok"], False, {200}, 3),
    "recovers-after-429": (["429", "ok"], False, {200}, 2),
    "stream-recovers": (["503", "ok"], True, {200}, 2),
    "timeout": (["slow"] * 3, False, {504}, 3),
    "too-big": (["context"], False, {400}, 1),
}


@pytest.mark.live
@pytest.mark.infrastructure
@pytest.mark.parametrize("existing", [False, True], ids=["managed", "existing"])
@pytest.mark.parametrize("case", sorted(CASES))
def test_a_down_model_is_retried_twice_and_never_switched(
    tmp_path, report_file, existing, case
):
    script, stream, statuses, contacts = CASES[case]
    report = {"existing": existing, "case": case, "passed": False}

    def save_report():
        report_file.write_text(json.dumps(report, indent=2) + "\n")

    save_report()
    body = {
        "model": "private",
        "messages": [{"role": "user", "content": "synthetic outage prompt"}],
    }
    if stream:
        body["stream"] = True
    with native_runtime_trial(tmp_path, existing, fixture_config) as trial:
        # Public is allowed and up: it must still receive nothing.
        trial.call("allow_public")
        trial.call("outage", json.dumps(script))
        response = trial.probe({"body": body, "timeout": 20, "observe_protocol": stream})
        status = response if isinstance(response, int) else response["status"]
        observed = trial.call("summary")
        report.update(
            {
                "status": status,
                "provider_contacts": observed["calls"],
                "steps": observed["outage_steps"],
                "selected_models": [row["model_id"] for row in observed["decisions"]],
            }
        )
        save_report()
        assert status in statuses
        # The same model only, the expected number of times.
        assert observed["calls"] == ["mock-private"] * contacts
        assert set(report["selected_models"]) == {"private"}
        # Each attempt passed its own selected-model check before contact.
        assert len(observed["decisions"]) >= contacts + 1
        assert observed["developer_key_forwarded"] == [False] * contacts
        report["passed"] = True
        save_report()


@pytest.mark.live
@pytest.mark.infrastructure
@pytest.mark.parametrize("existing", [False, True], ids=["managed", "existing"])
def test_a_started_stream_is_never_retried(tmp_path, report_file, existing):
    report = {"existing": existing, "passed": False}
    body = {
        "model": "private",
        "messages": [{"role": "user", "content": "synthetic stream prompt"}],
        "stream": True,
    }
    with native_runtime_trial(tmp_path, existing, fixture_config) as trial:
        trial.call("allow_public")
        trial.call("outage", json.dumps(["mid", "ok", "ok"]))
        response = trial.probe({"body": body, "timeout": 20, "observe_protocol": True})
        observed = trial.call("summary")
        report.update(
            {
                "response": response
                if isinstance(response, int)
                else {k: response[k] for k in ("status", "incomplete")},
                "provider_contacts": observed["calls"],
            }
        )
        report_file.write_text(json.dumps(report, indent=2) + "\n")
        # The first byte went out: the failure shows, and nothing is sent again.
        assert isinstance(response, dict) and response["incomplete"]
        assert "partial " in response["body"]
        assert observed["calls"] == ["mock-private"]
        assert observed["outage_steps"] == ["mid"]
        report["passed"] = True
        report_file.write_text(json.dumps(report, indent=2) + "\n")
