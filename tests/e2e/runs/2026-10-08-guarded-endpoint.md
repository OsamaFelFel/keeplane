# 8 October 2026 — guarded endpoint trial

**Edition:** Open Source · **Scope:** local Docker preview of model registration
and credential forwarding

The preview used agentgateway 1.6.0 image digest
`sha256:9d3e6044ddcdc0878b1787f77bd401252b95e22684203fb5e874c4c42d2ed90c`
and the real local Qwen2.5 Coder 0.5B runner. A disposable Python endpoint
accepted chat calls only with its fixed test key and forwarded them to Qwen.
The endpoint was reachable only on the Compose network. No user provider key
or external cloud model was used.

## Repeat the checks

```sh
docker compose --profile qwen up -d
docker compose exec -T app python - < tests/e2e/test_guarded_endpoint.py
python3 tests/e2e/test_local.py
python3 tests/e2e/test_qwen.py
```

The [guarded endpoint result](2026-10-08-guarded-endpoint.json) passed four
cases. Direct requests with no key and a wrong key returned HTTP 401. Keeplane
registered `guarded-qwen` in the gateway with the disposable test key, listed
the source without returning the key to the browser, and received nonempty
generated text through the gateway and endpoint. Repeating the registration
was idempotent; conflicting settings returned HTTP 409. The [existing local](2026-10-08-guarded-regression-local.json)
and [real Qwen](2026-10-08-guarded-regression-qwen.json) suites passed 7/7
and 2/2 cases after the change.

In the browser, Add model offered **Guarded endpoint trial · real Qwen**.
The dialog was 560px wide, and its text inputs and source dropdown were each
44px high × 502px wide. Submitting `ui-guarded` showed it in the Models table
with **Guarded endpoint** and **Disposable test key**. Selecting it and sending
a prompt displayed a generated Qwen answer labeled with the guarded source.

This is an endpoint and credential-forwarding trial. It does not test external
HTTPS, production secret storage, subscribed providers, account identity,
data-class limits, routing policy, or the coding CLI. The endpoint fixture and
its visible test key are not intended for customer installation.
