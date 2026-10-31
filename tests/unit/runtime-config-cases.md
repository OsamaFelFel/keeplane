# Managed runtime configuration

The builder creates a separate listener for the fixed managed gateway trial. It
does not install or enable anything. Raw model resources and the private operator
listener stay in place. Only exact stable model IDs can receive final checks.

Run `pytest tests/unit/test_runtime_config.py`. The cases check unchanged customer
configuration, stable native targets, and rejection of ambiguous, conditional,
virtual, indexed or missing targets and a conflicting listener.

The protected route also carries the outage retry of Spec 004 ST16: two retries
of the same model on 429, 500, 502, 503 and 504 with a 500 ms backoff, and a
per-attempt timeout up to the response headers. It adds no failover group or
virtual model, keeps the selected-model check on each model backend and never
retries a context-length refusal. The installer's readback accepts the served
route only with exactly one entry check, one retry with two attempts and one
timeout, in any order; a missing, changed, extra or duplicated policy is refused.
Run `pytest tests/unit/test_outage_retry.py`.

The compiled native proof also checked OpenAI/Anthropic shared credentials,
keyless/shared SSE, both overwritten markers, private operator validation and
zero provider contact after policy, credential, key or topology withdrawal.
Installer activation and the installed CLI journey are separate acceptance work.
