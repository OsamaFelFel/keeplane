# Enforcing-CNI gateway ingress cases

These cases use an **isolated** `keeplane-netpol` kind cluster with Calico, not the running `keeplane` product preview. The [cluster config](network-policy/kind.yaml) disables kindnet. The [workloads](network-policy/workloads.yaml) reuse the real chart's gateway and app pod labels but serve a tiny HTTP fixture instead of deploying the full product. The verifier refuses any kubeconfig context except `kind-keeplane-netpol` and deletes its test namespace.

The fixture uses the pinned Python digest `sha256:2d9aefe2fef018a7eb2c13064c89c71929800fd2e5dccdbf52ea5da5bb8d929a`. Its pull policy permits downloading that exact digest if the kind import is not recognized by kubelet. Earlier attempts with a locally loaded digest and then an alias were recorded as fixture startup failures before any policy measurement. The test allows up to four minutes for image resolution.

From the repository root, reproduce in a disposable cluster:

```sh
kind create cluster --name keeplane-netpol --kubeconfig /private/tmp/keeplane-netpol-kubeconfig --config tests/e2e/network-policy/kind.yaml --image kindest/node:v1.37.0@sha256:a1ed56cfb0e7b93589bdf97c8cd566405a265939e3620fc4f5de89adff580ae5
curl -fL https://raw.githubusercontent.com/projectcalico/calico/v3.33.0/manifests/calico.yaml -o /private/tmp/keeplane-netpol-calico-v3.33.0.yaml
shasum -a 256 /private/tmp/keeplane-netpol-calico-v3.33.0.yaml
kubectl --kubeconfig /private/tmp/keeplane-netpol-kubeconfig apply -f /private/tmp/keeplane-netpol-calico-v3.33.0.yaml
kubectl --kubeconfig /private/tmp/keeplane-netpol-kubeconfig wait --for=condition=Ready node --all --timeout=300s
python3 tests/e2e/test_network_policy.py --output tests/e2e/runs/<new-result>.json
```

The Calico manifest in this run had SHA-256 `2de8f47595fb9c41b3f47d7b767a1f8e72ecf84057af834738ff12689a234da5`; stop if a future fetch differs and inspect the change before using it. Set `KEEPLANE_NETPOL_KUBECONFIG` if using another local path. This cluster is disposable; delete only `keeplane-netpol` after recording the result.

| ID | Plain-English action | Expected result |
| --- | --- | --- |
| NET-01 | Before applying the chart policy, call the fixture gateway from the app-labeled pod and an unrelated sibling. | Both receive HTTP 200, proving service and DNS connectivity. |
| NET-02 | Apply the chart's managed gateway ingress policy. Repeat both calls. | The app still gets 200 and the sibling times out before reaching port 4000. |
| NET-03 | While the policy is active, give the sibling pod the trusted app label and retry. | The sibling gets 200. A caller allowed to change pod labels can enter this policy's allowlist. |
| NET-04 | Remove the trusted label from the sibling pod and retry. | The sibling is blocked again. |
| NET-05 | Remove the policy and retry from the sibling. | The sibling gets 200 again, showing the block came from policy enforcement. |

This establishes ingress selector behavior on an enforcing CNI. Kubernetes RBAC and admission control must prevent untrusted workloads from adopting the trusted label. The full product, existing customer gateway, upstream model path, egress controls and production CNI compatibility still require separate validation.
