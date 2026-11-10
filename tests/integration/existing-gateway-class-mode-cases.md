# Data classes on and off with a customer-run gateway

**Edition:** Open Source. Spec 005 ST18 and task 005-01: data classes are
optional, and turning them off keeps every definition and approval without
applying it.

[`test_existing_gateway_class_mode.py`](test_existing_gateway_class_mode.py)
starts a disposable Docker network with the pinned agentgateway set up as a
customer would run it (Keeplane installed with `GATEWAY_MODE=existing`), the
Keeplane app from this checkout and a mock provider. The gateway calls
Keeplane's two checks as the
[gateway guide](../../docs/guide/gateway-configuration.md#keeplanes-checks-on-a-customer-run-gateway)
describes: the route check, `/internal/runtime/authorize`, on the developer
route, and the final check, `/internal/runtime/authorize/selected`, on each
model after the gateway picks it. The customer registers `coder`, `reviewer`
and `late-coder` on its own gateway and also has `customer-owned`, which
Keeplane never sets up. One developer works on two projects, Payments and
Docs site.

The admin does everything through Keeplane's admin API, signed in as a
browser is, and each admin request runs in its own process. The gateway's
checks therefore see the switch and the approvals only through the shared
database. The whole run happens twice: once on SQLite and once on PostgreSQL
with the production storage settings (the app's own database user and a
password file; TLS to the database is covered by the
[PostgreSQL deployment cases](../e2e/postgres-deployment-cases.md)).

"Sent" means the mock provider received the request. Every check receives
only the project and the model, never the prompt.

| Case | Plain-English action | Expected result |
| --- | --- | --- |
| XCM-01 | On a new install, read Data classes and the projects, try to give Payments a class, set up `coder` and `reviewer`, then send Payments' requests to them and to `customer-owned`. | Classes are off and none are listed; no project has a class and giving one is refused. Both models are set up with no class and answer after both checks; `customer-owned` is refused at the route check and nothing is sent. |
| XCM-02 | Turn data classes on, give Payments Confidential, then send its request and one from Docs site to `coder`. | Public, Internal and Confidential appear with no approved models, and neither model was given a class. Payments is refused at the route check and nothing is sent; Docs site, which has no class, is sent. |
| XCM-03 | Approve `coder` for Confidential, rename Internal to Restricted, add Partners with `reviewer`, then send Payments' requests to `coder` and `reviewer`, and one for `coder` that the gateway changes to `reviewer` after the route check. | `coder` is sent; `reviewer` is refused at the route check; the changed request passes the route check for `coder` and the final check refuses `reviewer`, so nothing is sent. |
| XCM-04 | Turn data classes off, read Data classes, the projects and the models, send Payments' requests to `reviewer` and the changed request again, then set up `late-coder` while asking for Confidential. | No classes are listed and no project shows a class, but the models still carry their approvals. Both requests are sent: neither check applies a class while off. `late-coder` is set up with no class, whatever was asked, and is sent; `customer-owned` is still refused. |
| XCM-05 | Turn data classes on again and repeat the requests. | The same four classes, with the same IDs, names and approved models, and Payments is Confidential again. `coder` is sent; `late-coder` is refused for Payments and sent for Docs site; the changed request is refused at the final check; `reviewer` is not sent. |
| XCM-06 | Turn data classes off and on a second time. | Exactly what XCM-05 found: no starter class is added again and nothing is approved by the switch. |
| XCM-07 | After all of the above, check `customer-owned`. | It was never set up and no class lists it. It is refused for both projects, as it was in every state above. |

Run it with Docker, the locked images and the PostgreSQL app image
(`keeplane-preview:postgres-local`, or the image in
`KEEPLANE_RUNTIME_POSTGRES_IMAGE`):

```sh
docker build --target postgres -t keeplane-preview:postgres-local \
  -f components/control-plane/Dockerfile .
.venv/bin/python -m pytest tests/integration/test_existing_gateway_class_mode.py -m live
```

CI's PostgreSQL job runs both databases after building that image and fails
if either is skipped. The run writes one small JSON report per database under
`test-results/`.

What the gateway checks on each model must not do: Keeplane's own model setup
sends one short request through the gateway's model address (`gateway.url`)
with the gateway's runtime key and no developer session. A final check that
also runs for that request refuses it, and setup fails with "The model didn't
answer. Nothing was saved." This test's gateway marks developer traffic on its
developer listener and sends only marked requests to the final check, as
Keeplane's managed gateway does.

Not covered here: the kind cluster install (the
[existing-gateway cases](../e2e/existing-gateway-cases.md)), shared provider
keys, and personal-data detection, which has its own
[routing cases](personal-data-routing-cases.md).
