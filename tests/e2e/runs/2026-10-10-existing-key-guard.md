# 10 October 2026 — customer-run shared-key guard

**Scope:** Open Source local trial. The release gateway and provider-key delivery design remain open.

The customer-run gateway is in a separate namespace and cannot read Keeplane's provider-key PVC. Keeplane now returns HTTP 422 before accepting a shared cloud-provider key in this mode. Managed Docker and kind key flows remain available. [EXIST-04](../existing-gateway-cases.md) verified that the rejected request created no key file or gateway model and that an already approved local model still answered. The [focused live run](2026-10-10-existing-key-guard-live.json) passed 4/4 cases; the [chart render](2026-10-10-existing-key-guard-chart.json) passed 7/7 cases.

The [first full regression](2026-10-10-existing-key-guard-regression.json) passed 47/48 suites. The Docker runtime probe returned empty output after a long Qwen call, producing no case report. Its [focused retry](2026-10-10-existing-key-guard-docker-runtime-recheck.json) passed 2/2 cases. The [clean full rerun](2026-10-10-existing-key-guard-confirmed.json) passed **48/48 suites and 288/288 case records**, including Docker and kind runtime. Data Classes modes were restored. Post-run first-admin sign-in and gateway-ready health returned HTTP 200 on ports 3000 and 13000. The separate customer-run app was Ready with a ClusterIP Service and two Bound PVCs.

The failing run remains versioned as an intermittent probe failure. This stage does not make shared keys work in customer-run mode, select a release gateway, prove real cloud subscriptions, or resolve project-class bypass resistance.
