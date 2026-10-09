# Existing-gateway install gate — 9 October 2026

The [plain-English Kubernetes cases](../kubernetes-cases.md) K8S-10–13 check
the pre-release `existing` Helm mode against the separately installed
agentgateway 1.6.0 in the isolated kind cluster. The pre-install/pre-upgrade
job uses Keeplane's app image and checks `/api/runtime`, `/v1/models`, and the
model-management read API. This local profile also asks the registered
`customer-fixture` mock model for a one-token answer. It does not write
gateway configuration or expose a provider key. A wrong pinned version or a
missing probe model makes the check fail. A fresh Helm install with a wrong
version failed before any Keeplane app Deployment existed; its temporary
namespace and release were removed.

The [targeted run](2026-10-09-existing-preflight-targeted.json) passed six
cases: four preflight cases and two post-install gateway-outage cases. The
first [full regression](2026-10-09-existing-preflight-regression.json) passed
25/26 suites and 125/126 case records. K8S-09 failed because its test used
`kubectl exec deployment/...` immediately after a rollout and could select
the old pod, which still pointed at the working gateway. The app readiness
case K8S-08 passed. The test now waits until the Service endpoint points to
the new pod and checks that pod's `GATEWAY_URL` before probing the Service.
The [outage recheck](2026-10-09-existing-preflight-outage-recheck.json)
passed 2/2 cases, and the [final full regression](2026-10-09-existing-preflight-regression-final.json)
passed **26/26 suites and 126/126 case records**. Afterward, the Docker
preview returned 200, the protected preview redirected to sign-in (302),
the managed kind preview returned 200, and the existing-gateway app had one
Ready replica.

This is an integration trial, not a release gateway compatibility contract.
The read API check cannot prove that Keeplane may register a model. TLS,
authentication, secret handling, and the license-approved gateway artifact
remain release gates. The optional inference check makes a model call and
may consume quota when pointed at a non-fixture model.
