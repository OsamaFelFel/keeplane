# Gateway-down admin UI availability — 9 October 2026

The kind chart previously used gateway-dependent `/health` as the app readiness probe. When the gateway was down, Kubernetes removed Keeplane's app from its Service, preventing the admin UI from showing the gateway warning required by Spec 004 ST25. The chart now probes app-only `/health/app`; `/health` retains its dependency check. The app image also now includes all imported control-plane modules, so the updated app can start from the built image without host bind mounts.

The [plain-English cases](../kubernetes-cases.md) and [repeatable verifier](../test_gateway_down.py) use a temporary namespace in the isolated `kind-keeplane` cluster and an unreachable existing-gateway address. The [focused JSON run](2026-10-09-gateway-down.json) passed **K8S-08 and K8S-09**: the app had one Ready replica and one Service endpoint; the page and `/health/app` returned 200 while `/health` and `/api/models` returned 503. The verifier requests through the Kubernetes Service, so it would fail if readiness removed the endpoint.

**K8S-UI-01 passed in a browser.** I opened the temporary app through a loopback port forward after the gateway failed. The page visibly showed “The model gateway isn't answering” and “Try again”; Add model was disabled and the table said “Models unavailable.” The temporary release, namespace and port forward were removed after inspection. No customer gateway or running Keeplane preview was changed by this check.

The first verifier invocation failed in its JSON parser because it merged a kubectl warning from stderr into stdout. It did not produce a product-case result. The runner now keeps stderr separate; two later focused invocations passed. The [full regression result](2026-10-09-gateway-down-regression.json) passed **25/25 suites and 122 case records**, including both gateway-down cases, Docker and kind transport, Qwen, gateway replica failover, accounts, data classes, models and Audit.

Run `deploy/local/kind-up.sh` after changing the app or chart, then use the isolated kubeconfig:

```sh
python3 tests/e2e/test_gateway_down.py
python3 tests/e2e/run_regression.py --output tests/e2e/runs/NEW-full-regression.json
```

This is a local integration check of UI availability. It does not select a release gateway, add production authentication to kind, or prove gateway recovery under a real network outage.
