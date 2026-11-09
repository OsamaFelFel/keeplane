# CLI sign-in and the guarded gateway on the default preview

**Edition:** Open Source. Spec 009 ST29 and ST30, task 009-01, ADR 028; ST31
"A local model", task 009-10, ADR 029 (PSI-LIVE-05). The
precondition for every DEV case: a developer signs in from the CLI against
`python3 deploy/local/up.py`, started with no options.

Run after a fresh start, with host port 14424 free:

```sh
python3 deploy/local/up.py
.venv/bin/python -m pytest tests/e2e/test_preview_sign_in_live.py -m live
```

The suite skips, with the reason, when the preview, its credentials, Docker,
the model enroller or that port are not available. If the preview already has
approved models, PSI-LIVE-03 is reported as not run and the suite is skipped
after the other cases pass; the live-preview workflow runs it first on a fresh
preview, where every case must run.

## Fixtures

- A temporary developer, created by the first admin.
- The source-tree CLI (`components/cli/keeplane.py`) with a private home and
  two private profiles. Its browser is a fixture that opens the URL the CLI
  gives it and uses Keeplane's real sign-in and consent pages and the CLI's
  loopback callback; the device code is approved on the real device pages.
- A runner on the host at the preview's allowed address
  `http://host.docker.internal:14424` that serves one model and counts every
  request it receives.
- One project, registered by the developer from the CLI.

| ID | Plain-English action | Expected result |
| --- | --- | --- |
| PSI-LIVE-01 | The developer runs `keeplane login --server http://127.0.0.1:3000 --profile …` and signs in through the browser. | The CLI says `Signed in to Keeplane.`, `whoami` names the developer, and the saved credential file is private (mode 0600). |
| PSI-LIVE-02 | The developer runs `keeplane login --device` into a second profile and enters the code in a browser. | The CLI names the preview's own confirm-device address, the browser shows "CLI access allowed", the CLI says `Signed in to Keeplane.` and `whoami` names the developer. |
| PSI-LIVE-03 | No model is approved yet. The developer lists the project's models and sends a request through the guarded gateway. | The enroller's last report is `No model is enrolled for protected access.`, the gateway gives no answer, and the runner receives nothing. `keeplane models` prints the documented empty catalog (`"models": []`, with `"chosen_by": null` since nothing can be marked) and exits 0. This holds on a fresh preview too, before an admin has saved any data-class or model setting: the defaults apply (data classes off) and nothing is on stderr. |
| PSI-LIVE-04 | The admin adds one runner model approved for Public data; the developer lists models and sends a request with, then without, the CLI's credential. | The enroller reports one more model enrolled (`Protected access is ready: 1 model is enrolled.` on a fresh preview); `keeplane models` lists it; the signed-in request returns 200 with the runner's answer and reaches the runner once; the request with no credential is refused (401) and reaches nothing. |
| PSI-LIVE-05 | The developer sends one request to that model the way `keeplane code` does, through the CLI's usage relay, the CLI reports it, and the developer runs `keeplane usage`. | The request returns the runner's answer; the relay counts 1 request with 2 input and 2 output tokens (the runner's usage); the report is accepted with no warning. Read before and after, the developer's totals for that model grow by exactly 1 request, 2 input and 2 output tokens for today and for this month, so usage already recorded this month doesn't matter; the model is priced as local. `keeplane usage` exits 0 and shows the model for today and this month with "—" for cost. |

## Restoring the preview

Afterwards the suite logs both CLI profiles out (which revokes them), removes
the model from Keeplane and the gateway, and removes the developer. Removing a
model makes the enroller wait about 3 minutes and 16 seconds before its next
change (ADR 027).
The suite returns only once the enroller reports the starting number of
models again (up to 5 minutes), so the next suite starts with a settled
enroller. A restore step that can't be confirmed fails the run.

## Not covered here

- Coding with `keeplane code` and OpenCode: the
  [installed CLI journey](installed-cli-cases.md) and later Spec 009 tasks.
- The gateway address coming from the server (task 009-02) and the expired
  sign-in offer (task 009-04).
