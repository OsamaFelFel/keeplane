# Full Keeplane chart on a local enforcing CNI

Edition: Open Source. Run `python3 tests/e2e/test_full_product_edge.py --output <new JSON path>` against the separate `kind-keeplane-netpol` cluster with Calico and the disposable ingress-nginx controller. The script creates and removes its own namespace. Its model and PostgreSQL fixtures are local test inputs; this is not a production installation. It never touches the main Docker or kind previews.

| ID | Plain-English action | Expected result |
| --- | --- | --- |
| FULL-01 | Install the actual Keeplane chart with one managed gateway, gateway ingress policy, and an HTTPS app Ingress; visit its root without signing in. | The trusted TLS route reaches Keeplane and asks the visitor to sign in. |
| FULL-02 | Sign in as the local first admin through HTTPS and read the identity API. | The session works through the Ingress and the identity API answers. |
| FULL-03 | Read the model list through the signed-in app route. | The app can still reach its managed gateway under the NetworkPolicy. |
| FULL-04 | From an unrelated model fixture pod in the same namespace, call the internal gateway Service. | The network connection is blocked before the gateway can answer. |
| FULL-05 | Read the installed policy. | It selects the managed gateway pods for this Helm release. |

Passing these cases would cover only this local CNI/controller and one gateway replica. A pod creator who can copy the trusted app label, a copied gateway key, direct vendor access, project identity, data-class policy, production certificate rotation and two-replica cold startup require separate evidence.
