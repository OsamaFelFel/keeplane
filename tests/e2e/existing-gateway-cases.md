# Protected customer-run gateway trial

**Edition:** Open Source. These cases use the isolated `kind-keeplane` cluster.
The supplied gateway is installed separately in another namespace and already
contains `customer-fixture`. A temporary port-forward opens only the Keeplane
app on loopback while tests run; no gateway port is published.

| ID | Plain-English action | Expected result |
| --- | --- | --- |
| EXIST-01 | Run the full local account suite through the protected existing-gateway app. | All 21 account cases pass, including the infrastructure admin, roles, session rules and no Team API. |
| EXIST-02 | Try the model API without a session, then sign in and read models, Data Classes and Audit. | Anonymous access returns 401. The admin can read all three APIs; `customer-fixture` remains in the supplied catalog and classes start off. |
| EXIST-03 | Ask the Keeplane-approved `customer-managed` fixture, then ask the unrelated `customer-fixture` without setting it up. | The approved model answers; the gateway-only model is refused without an upstream answer. |
| EXIST-04 | Attempt to add a cloud model with a shared provider key while the gateway runs in another namespace. | Keeplane explains that key delivery is unsupported in this trial before creating a key file or gateway model. Existing models remain usable. |

[K8S-05, K8S-17 and K8S-06](kubernetes-cases.md) check Helm resources,
authenticated setup and catalog separation. [PKG-07](chart-package-cases.md)
checks the protected existing-mode render. The React browser suite runs with
the port-forward on port 13001. Shared provider-key delivery and project-class
bypass resistance are not covered by these cases.
