# App-only TLS Ingress cases

Use the separate `keeplane-netpol` kind cluster described in [network-policy-cases.md](network-policy-cases.md), with Calico ready. Install the pinned [upstream ingress-nginx kind manifest](https://github.com/kubernetes/ingress-nginx/blob/controller-v1.15.1/deploy/static/provider/kind/deploy.yaml) only in this disposable cluster; this is a controller fixture, not Keeplane's selected release controller. Its manifest SHA-256 for this run is `2a3ae008c8786431115502644e77ab398fdebfb721a5d1195ed3089cde3299df`.

```sh
curl -fL https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.15.1/deploy/static/provider/kind/deploy.yaml -o /private/tmp/keeplane-ingress-nginx-kind-v1.15.1.yaml
shasum -a 256 /private/tmp/keeplane-ingress-nginx-kind-v1.15.1.yaml
kubectl --kubeconfig /private/tmp/keeplane-netpol-kubeconfig apply -f /private/tmp/keeplane-ingress-nginx-kind-v1.15.1.yaml
kubectl --kubeconfig /private/tmp/keeplane-netpol-kubeconfig -n ingress-nginx rollout status deployment/ingress-nginx-controller --timeout=240s
python3 tests/e2e/test_chart_ingress.py --output tests/e2e/runs/<new-result>.json
```

Stop and inspect the manifest if its hash differs. The verifier refuses any context other than `kind-keeplane-netpol`, generates a one-day self-signed certificate in a temporary directory, and removes its fixture namespace and port-forward afterward.

The [fixture](ingress/workloads.yaml) runs a pinned Python app that answers `app:<path>` and a separate gateway marker that answers `gateway:<path>`. The verifier installs the actual rendered Keeplane Ingress in the test namespace.

| ID | Plain-English action | Expected result |
| --- | --- | --- |
| EDGE-01 | Connect to the Keeplane host through the Ingress with the generated certificate trusted by the client. | TLS verification succeeds and the app responds. |
| EDGE-02 | Ask that public host for an upstream gateway-management path. | The Ingress still selects the app Service, never the gateway fixture. This does not prove the app's own route authorization. |
| EDGE-03 | Request the same host over plain HTTP. | This controller redirects to HTTPS. Other controllers need their own proof. |
| EDGE-04 | Request the HTTPS listener with an unrelated host name. | The controller does not route it to Keeplane's app. |

The trial does not install the full Keeplane product, prove a customer-provided controller, or validate a future project-bound model runtime path.
