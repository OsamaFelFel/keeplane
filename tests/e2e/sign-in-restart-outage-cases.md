# CLI sign-in through restarts and outages

**Edition:** Open Source. Spec 009 ST29 and ST30, task 009-15 (the release check
"Restart and outage" that ADR 022 set and ADR 028 still owes). Each case
restarts the app or PostgreSQL, or stops
the gateway, in the middle of a browser or device sign-in, a refresh or a
coding task, and checks what the developer sees and what Keeplane keeps.

Build the PostgreSQL app image with CLI sign-in, then run:

```sh
docker build --target postgres-cli-auth-trial -t keeplane-preview:postgres-cli-auth-local \
  -f components/control-plane/Dockerfile .
.venv/bin/python -m pytest tests/e2e/test_sign_in_restart_outage.py -m live
```

Set `KEEPLANE_SIGN_IN_POSTGRES_IMAGE` to use another tag. The suite skips, with
the reason, when Docker or the image is missing; CI's `sign-in-outage` job fails
on a skip or a case that didn't run. It takes about three minutes.

## Fixtures

- A disposable install of its own ([fixture](../fixtures/sign_in_outage.py)), in
  its own Compose project on loopback ports the system picks, so the local
  preview on port 3000 is never touched:
  - PostgreSQL, with its data on a volume, so a restart keeps every sign-in;
  - the PostgreSQL app image with CLI sign-in, served by gunicorn, its database
    reached with the production storage settings (TLS to PostgreSQL is checked
    by the chart and deployment cases);
  - a pinned agentgateway run as a customer runs it (`GATEWAY_MODE=existing`):
    its developer route asks Keeplane's route check before every model call,
    with `failureMode: deny`; it keeps its models on a volume;
  - a mock provider that counts every call it receives.
- One model, `coder`, added to the gateway by the customer and set up by the
  first admin with no key.
- For each case, a new developer and a private home with the source-tree CLI.
  Its browser is a fixture on Keeplane's real sign-in and consent pages that
  can stop with the consent page open, or after allowing access and before
  returning to the CLI. The device code is approved on the real device pages.
- A stand-in coding runtime ([fixture](../fixtures/outage_runtime.py)) that
  `keeplane code` runs like OpenCode: it sends the task's model calls through
  the CLI's usage relay with the grant and project the CLI gives it, and can
  wait between two calls while the case restarts or stops a service. The real
  runtime's retries and tools are covered by the developer journey.

"Restarts" means stopped and started again; "down" means stopped until the
CLI has finished.

## Sign-in

| ID | Plain-English action | Expected result |
| --- | --- | --- |
| SRO-01 | With the consent page open in the browser, the app restarts; then the developer allows CLI access. | The CLI says `Signed in to Keeplane.`; `whoami` names the developer; the developer has one access and one refresh token. |
| SRO-02 | The same, with PostgreSQL restarting. | The same. |
| SRO-03 | The developer allows CLI access, the app stops before the CLI exchanges the code, then starts again. | The CLI exits 1 with "Keeplane isn't available right now, so you aren't signed in. Run `keeplane login` to try again in a few minutes." Nothing is half saved: no credential on the machine, no token in the database, and `whoami` says the developer is signed out. `keeplane login` then signs in. |
| SRO-04 | The same, with PostgreSQL down at the exchange (the app answers 503). | The same. |
| SRO-05 | `keeplane login --device` is waiting for approval when the app stops; it starts again, then the developer approves the code. | The CLI keeps waiting through the restart and then says `Signed in to Keeplane.`; `whoami` names the developer. |
| SRO-06 | The same, with PostgreSQL restarting. | The same. |

## Refresh

| ID | Plain-English action | Expected result |
| --- | --- | --- |
| SRO-07 | A signed-in developer runs `keeplane refresh` while the app is down, then again once it is back. | The first exits 1 with "Keeplane isn't available right now, so your sign-in wasn't refreshed. It's kept as it was. Run `keeplane refresh` again in a few minutes." The saved sign-in is unchanged and still works. The retry says `Keeplane credential refreshed.` and saves a new pair with the same gateway address. The old access token is refused (401) by Keeplane and by the gateway; the new one gets an answer through the gateway. One access and one live refresh token remain. |
| SRO-08 | The same, with PostgreSQL down (the app answers 503). | The same. |
| SRO-09 | Keeplane rotates the pair but the answer never reaches the CLI, as when the app restarts after saving it; the developer runs `keeplane refresh` with the old pair. | Reusing the old refresh token withdraws the whole sign-in: the CLI exits 1 with "Your Keeplane sign-in has expired. Run `keeplane login` to sign in again."; the old and the never-received access tokens are refused (401) by Keeplane and the gateway; no token is left. `keeplane code` then says "Your Keeplane sign-in has expired, so nothing was sent. Run `keeplane login` to sign in again." and nothing reaches the provider. `keeplane login` signs in again. |
| SRO-10 | The developer runs `keeplane refresh` while the gateway is down. | Refresh doesn't need the gateway: it succeeds and keeps the gateway address. The old access token is refused at the gateway once it is back, and `keeplane code` works with the new one. |

## Coding

| ID | Plain-English action | Expected result |
| --- | --- | --- |
| SRO-11 | Between the two model calls of a `keeplane code` task, the app restarts. | The second call is checked and answered with the same sign-in: the task finishes, says `Answered by coder.`, and the provider gets both calls. |
| SRO-12 | The same, with PostgreSQL restarting. | The same. |
| SRO-13 | The same, with the gateway restarting. | The same. |
| SRO-14 | Between the two calls the app goes down. The gateway can't run Keeplane's check, so it refuses the second call (403). | The task exits 1 with "Keeplane isn't available right now, so this task stopped and nothing more was sent. Try again in a few minutes, or ask your admin to check Keeplane." Not an expired sign-in, a refused key or a model that is down: the call never reached a model, so the model-down message doesn't apply (D177). The provider got only the first call. Once the app is back, the same sign-in runs a task. |
| SRO-15 | The same, with PostgreSQL down: Keeplane's check answers 503 "Keeplane storage is unavailable…", which the gateway passes on before any model is tried. | The same message. |
| SRO-16 | The same, with the gateway down: the CLI's relay can't reach it (502). | The task exits 1 with "Keeplane's gateway can't be reached right now, so this task stopped and nothing more was sent. Try again in a few minutes, or ask your admin to check the gateway." The CLI also says it couldn't record the task's usage, because Keeplane records usage only while it can read the gateway's models. Once the gateway is back, the same sign-in runs a task. |
| SRO-17 | A task starts while the gateway is down, then one while the app is down. | Neither runtime starts and nothing reaches the provider. With the gateway down, Keeplane can't choose a model and the CLI says "Keeplane is temporarily unavailable; retry later."; with the app down, "Cannot reach Keeplane securely; check the server and certificate configuration." Both exit 1. |

## What this doesn't cover

- The managed gateway, and two app copies: the DEV-01 to DEV-08 runs in both
  gateway modes on PostgreSQL and two app copies are a separate part of task
  009-15. The managed gateway's own outage case is in the
  [native runtime outage cases](../integration/native-runtime-outage-cases.md).
- An answer cut off after Keeplane saved a sign-in, other than the refresh in
  SRO-09: the CLI never resends an authorization code, and a device code that
  was already used is refused, so nothing is saved twice.
