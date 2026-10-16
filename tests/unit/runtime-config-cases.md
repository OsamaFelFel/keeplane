# Managed runtime configuration

The builder creates a separate listener for the fixed managed gateway trial. It
does not install or enable anything. Raw model resources and the private operator
listener stay in place. Only exact stable model IDs can receive final checks.

Run `pytest tests/unit/test_runtime_config.py`. The cases check unchanged customer
configuration, stable native targets, and rejection of ambiguous, conditional,
virtual, indexed or missing targets and a conflicting listener.

The compiled native proof also checked OpenAI/Anthropic shared credentials,
keyless/shared SSE, both overwritten markers, private operator validation and
zero provider contact after policy, credential, key or topology withdrawal.
Installer activation and the installed CLI journey are separate acceptance work.
