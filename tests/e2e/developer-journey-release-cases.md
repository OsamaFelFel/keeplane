# Developer journey on release installs, in both gateway modes

**Edition:** Open Source. Spec 009 ST29 to ST31, task 009-15 ("Run DEV-01 to
DEV-08 with the customer's own gateway (existing mode) and with the managed
gateway, on PostgreSQL and two app copies"), ADR 022, ADR 027, ADR 028. The
cases are the [developer journey cases](developer-journey-cases.md) DEV-01 to
DEV-08, with DEV-03b on DEV-03's task, run by the same code
(`run_cases` in `test_developer_journey.py`) on two disposable installs
instead of the default preview.

**Not covered:** DEV-09 and DEV-10 (developers' own keys) don't run on these
installs. A customer-run gateway currently supports only **No key** models:
Keeplane's shared key and developers' own keys aren't supported in existing
mode yet (see the [gateway guide](../../docs/guide/gateway-configuration.md)).
They stay on the default preview's managed gateway. In `existing`, DEV-04's
cloud model is set up with **No key** and the customer's gateway holds the
provider key; Keeplane doesn't hold, check or rotate it, and it isn't
Keeplane's shared-key option.

Run with Docker, `openssl`, the admin UI built, the PostgreSQL app image with
CLI sign-in and the pinned coding runtime, OpenCode V2 2.0.27 (the musl build
the `coding-runtime` check downloads and hash-checks):

```sh
(cd components/admin-ui && npm ci && npm run build)
docker build --target postgres-cli-auth-trial \
  -t keeplane-preview:postgres-cli-auth-local -f components/control-plane/Dockerfile .
KEEPLANE_OPENCODE_V2_BIN=/path/to/opencode \
  .venv/bin/python -m pytest tests/e2e/test_developer_journey_release.py -m live
```

The runtime is built for musl, so on most Linux machines it runs only in
Alpine. The `release-journey` job of `.github/workflows/checks.yml` runs the
suite there, on the host network, as the live-preview workflow runs the
preview journey. Without the runtime, DEV-01, DEV-02, DEV-05 and DEV-06 still
run, DEV-03, DEV-03b, DEV-04 and DEV-08 are reported as not run, and DEV-07
needs an `opencode` on `PATH`, though it never starts it. A case not run skips
the test, and the job fails on any skipped case.

## The installs

Each install is its own Compose project with loopback ports the system picks,
so it never touches the local preview on port 3000 or any other project. Its
files are in a new folder under the checkout's `.keeplane/` (not kept in Git),
removed with the project afterwards. Both have:

- PostgreSQL. The app copies use its owner role.
- Two copies of the PostgreSQL app image with CLI sign-in, served by gunicorn,
  with one signing secret, after one setup step has migrated the database and
  registered the CLI clients.
- One address in front of the copies for the browser, the CLI and the
  gateway's checks. It sends each request to the next copy in turn and counts
  what each copy answered.
- The preview's HTTPS OpenAI fixture with its own test CA, which only the app
  copies and the gateway trust, and a mock local model nobody sets up.

| Install | Gateway | Cloud model key | Model the project doesn't allow (DEV-08) |
| --- | --- | --- | --- |
| `existing` | A pinned agentgateway the customer runs, set up as the [gateway guide](../../docs/guide/gateway-configuration.md#keeplanes-checks-on-a-customer-run-gateway) says: the developer listener sets the marker before routing, the route check is on the developer route with the guide's retry and timeout, each model's backend sends marked requests to the final check and unmarked ones to the key-only check, and a last backend step passes on only the provider's own headers. Each model Keeplane will set up is named in the gateway's file up front. Keeplane's management address has no published port. | The customer's gateway holds the fixture provider's key and adds it on that model's backend. The admin adds the cloud model with no key: Keeplane keeps no shared key for a gateway it doesn't run. | `customer-model`, which the customer added to its own gateway. |
| `managed` | The Docker preview's runtime profile: the runtime installer writes the guarded gateway's files, and the model enroller, in the gateway's network with its own read-only PostgreSQL role, enrols each model the admin adds. | The admin adds the cloud model with the shared key, which Keeplane keeps for its own gateway. | `local-fixture`, from the installer's gateway file. |

The journey then runs as on the preview, with the install's address in every
step: two temporary developers, the sample repo and its clone, the
tool-capable fixture model on the host at the address the install allows
(`http://host.docker.internal:<port>`), and the fixture cloud model
`gpt-5-mini`. DEV-03 also checks that none of Keeplane's own headers (the
developer's sign-in, the project, the gateway credential or a gateway marker)
reaches the fixture model. On a customer-run gateway there is no enroller, so
a model change applies at once and the suite doesn't wait for one. DEV-07
expires the sign-in through the first app copy; DEV-05 to DEV-08 count
requests in the gateway's developer listener log (`developer-chat` on the
customer's gateway, `keeplane-runtime` on the managed one).

| ID | Plain-English action | Expected result |
| --- | --- | --- |
| DJR-01 | Start the `existing` install, then run DEV-01 to DEV-08 on it. | Every case passes as in the [developer journey cases](developer-journey-cases.md), with the install's own address in place of `http://127.0.0.1:3000`. Through the customer's gateway, DEV-03's edit is made and no Keeplane header reaches the model; DEV-04's cloud model, which Keeplane added with no key, shows a cost marked as an estimate. Clean-up removes the models and developers, and both app copies answered requests through the one address. |
| DJR-02 | Start the `managed` install, then run DEV-01 to DEV-08 on it. | Every case passes as in the developer journey cases. The enroller reports the new models enrolled before the cases start. Clean-up removes the models and developers, and both app copies answered requests through the one address. |

Each install's report, `developer-journey-release-<install>.json`, records
each case's observations without any credential, and how many requests each
app copy answered, under `test-results/` (not kept in Git).
