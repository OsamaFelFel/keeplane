# Full Keeplane chart on a local enforcing CNI

Edition: Open Source. Run `python3 tests/e2e/test_full_product_edge.py --output <new JSON path>` against the separate `kind-keeplane-netpol` cluster with Calico and the disposable ingress-nginx controller. The script creates and removes its own namespace. Its model and PostgreSQL fixtures are local test inputs; this is not a production installation. It never touches the main Docker or kind previews.

| ID | Plain-English action | Expected result |
| --- | --- | --- |
| FULL-01 | Install the actual Keeplane chart with two managed gateway replicas, gateway ingress policy, and an HTTPS app Ingress; visit its root without signing in. | The trusted TLS route reaches Keeplane and asks the visitor to sign in. |
| FULL-02 | Sign in as the local first admin through HTTPS and read the identity API. | The session works through the Ingress and the identity API answers. |
| FULL-03 | Read the model list through the signed-in app route. | The app can still reach its managed gateway under the NetworkPolicy. |
| FULL-04 | From an unrelated model fixture pod in the same namespace, call the internal gateway Service. | The network connection is blocked before the gateway can answer. |
| FULL-05 | Read the installed policy. | It selects the managed gateway pods for this Helm release. |
| FULL-06 | Inspect the installed gateway pods after Helm reports the release ready. | Both gateway replicas are Ready. |
| FULL-07 | Approve the local fixture model, then ask it through the signed-in HTTPS app route. | The app receives the fixture answer through the managed gateway. |
| FULL-08 | Remove one gateway pod and immediately ask the same model again while another original replica is Ready. | The app receives the fixture answer with one original gateway replica remaining. |
| FULL-09 | Register another fixture model through Keeplane after one gateway pod is removed. | Registration succeeds while one gateway replica is Ready. |
| FULL-10 | Wait for the replacement gateway pod, then read the runtime model list and management resources from each replica separately. | Both replicas show the new model in both views. |
| FULL-11 | Remove that Keeplane-owned model, inspect both replicas again, and ask the removed model through Keeplane. | Neither replica lists the model and Keeplane refuses the ask. |

Passing these cases covers one local CNI/controller, single gateway-pod removal and model-catalog convergence. Per-replica diagnostic reads use local port-forwards and test keys; they do not test client access through the network boundary. The run does not prove project and data-class policy propagation, credential revocation, protection from a pod creator who can copy the trusted app label, a copied gateway key, direct vendor access, production certificate rotation or production storage durability.
