# Developer CLI cases

**Edition:** Open Source. **Spec:** 009 Developer CLI (ADRs 028, 029 and 030),
task 009-14.

This page holds no checks of its own. It names, for each Spec 009 scenario, the
cases elsewhere that prove it, lists the closest evidence separately, and says
plainly which scenarios are not proven yet and what is still missing.

## Spec 009 scenarios (ST29–ST31)

Each scenario in Spec 009 and the cases that prove it. Each case is in its own
catalog:

- The developer journey on the default preview: DEV the
  [developer journey cases](developer-journey-cases.md) and PSI-LIVE the
  [preview sign-in cases](preview-sign-in-live-cases.md), both run by the
  `live-gateway` job of `.github/workflows/live-preview.yml`.
- Sign-in against the real sign-in server: ADM-INT the
  [admin and sign-out cases](../integration/cli-admin-sign-in-cases.md) and
  EXP-INT the [expired sign-in integration cases](../integration/cli-sign-in-again-cases.md),
  run by the `cli-sign-in` job of `.github/workflows/checks.yml`.
- Sign-in in the CLI: NB the [no-browser cases](../unit/cli-no-browser-cases.md),
  and EXP and OUT the [expired sign-in and signed-out cases](../unit/cli-sign-in-again-cases.md).
- Coding through the gateway: KEY-01 to KEY-08 the
  [runtime settings cases](../unit/cli-runtime-settings-cases.md), KEY-09 the
  [coding runtime cases](cli-runtime-cases.md) (the `coding-runtime` job of
  `checks.yml`, with the pinned runtime), RPJ the
  [repo project cases](../integration/cli-repo-project-cases.md), PK the
  [provider key cases](../integration/runtime-provider-key-cases.md) and MC the
  [model choice cases](../integration/model-choice-cases.md).
- Usage: USE the [usage cases](../unit/cli-usage-cases.md), and DU and DU-C the
  [developer usage cases](../integration/developer-usage-cases.md).

A scenario counts as proven only by checks CI runs on the current revision: the
unit and integration shards, and the `cli-sign-in`, `coding-runtime` and
`live-gateway` jobs. The three named jobs fail if a case is skipped; the shards
run every unit and integration file but don't fail on a skip. The "Proven by"
column names only such checks. "Closest evidence" names what else comes near and
what each proof leaves out, such as checks CI doesn't run or a stand-in for the
real server or runtime.

The developer journey suite runs DEV-01 to DEV-08: DEV-06 to DEV-08 are the
device sign-in, expired sign-in and admin journey cases in task 009-13's table.

`tests/unit/test_developer_cli_scenario_map.py` fails if a scenario is missing
here, a "Proven by" cell names a case CI doesn't run, or a case named here has
no row in its own catalog or no test. Only a test named after a case, or the
case ID in a string, counts; a comment never does.

| Story | Scenario | Proven by | Closest evidence |
| --- | --- | --- | --- |
| ST29 | Sign in through the browser | DEV-01 and PSI-LIVE-01 (on the default preview, the CLI opens a browser fixture at the URL it gives; the fixture signs in on Keeplane's real sign-in and consent pages and the CLI says it is signed in), ADM-INT-01 (the same against the real sign-in server, for a developer and an admin) | The browser is a fixture that submits the real pages' forms; a rendered Chromium run (`test_cli_oauth_rendered_browser.py`) is optional and CI doesn't run it. |
| ST29 | No browser on the machine | DEV-06 (on the default preview, over SSH with no display and with a browser still named in `BROWSER`, a plain `keeplane login` says no browser can open, shows a code and an address, and approving the code from another browser signs the CLI in), ADM-INT-01 (with no browser, `keeplane login` against the real sign-in server shows a code and an address with no `--device`, and the code signs the CLI in), NB-02, NB-03 (no browser, or one that fails to start, falls back to the device code), PSI-LIVE-02 (device sign-in on the default preview, approved on the real device pages) | DEV-06 forces the no-browser path with `SSH_CONNECTION`; the no-display and failed-browser paths are checked against the real server (ADM-INT-01) and a controlled one (NB-02, NB-03). |
| ST29 | An admin signs in | DEV-08 (on the default preview, the first admin signs in from the CLI, lists exactly the developer's models, is refused a model the project doesn't allow with nothing sent, and runs DEV-03's coding task with the pinned runtime through the guarded gateway; **Projects** then lists them on the repo's project), ADM-INT-01 (the first admin signs in through the browser and with no browser, registers the repo, lists only the approved model, is refused another model and runs a coding turn, exactly as a developer does) | — |
| ST29 | Sign out | DEV-05 (after `keeplane logout`, `code` and `models` send nothing, the model and gateway get nothing, and the old sign-in is refused at the gateway), ADM-INT-05 (after sign-out nothing reaches the server or gateway until `keeplane login`, then `code` runs), EXP-INT-02, OUT-01 | — |
| ST29 | The sign-in has expired | DEV-07 (on the default preview, with the developer's sign-in expired on the server, `code` sends nothing to the model, the guarded gateway or the cloud fixture; in a script it says the decided expired message, and in a terminal it offers to sign in again, signs in, and asks before starting the task), EXP-INT-01 (an expired sign-in on the real sign-in server: `code` says it has expired and sends nothing, and in a terminal offers to sign in again), EXP-01, EXP-02, EXP-06, EXP-07 (the offer, and nothing sent when the gateway refuses part-way or at once) | DEV-07 and EXP-INT-01 age the token in the database instead of waiting 8 hours. |
| ST30 | Work in a repo | DEV-03 (in a sample repo, `keeplane code` sends every request through the guarded gateway to the model, shows the answer and the edit, and the test passes), KEY-09 (the pinned runtime contacts only the CLI's relay to the gateway) | — |
| ST30 | A repo not set up in Keeplane | DEV-02, DEV-03 (a repo nobody set up lists its models and codes fully; **Projects** then shows it, not set up, with that developer), RPJ-01 (two clones of one remote are one project, not set up), RPJ-02 (with data classes on and no class set, the repo's project lists every approved model) | — |
| ST30 | Cloud models use API keys | Not proven yet: no check CI runs sends a coding task to a cloud model on the developer's own key. CI proves the rest: DEV-04 (a task on a cloud model uses the organization's shared key through the guarded gateway), KEY-09 (the runtime ignores saved subscription sign-ins and provider keys), KEY-02, KEY-05, KEY-08 (no provider sign-in is turned on or accepted, and the CLI has no subscription sign-in command). | Closest, in the integration shards: `test_personal_dispatch.py` (each developer gets only their own stored key for a model), `test_personal_transport.py` (the private adapter hands the gateway only the signed-in developer's key) and `test_installed_personal_runtime.py` (the managed gateway's entry checks the current owner's key and denies a missing or removed one). Nothing in CI sends that key to a provider in a task. Also in CI: PK-01, PK-02 (the server keeps each developer's own key and checks it with the provider), MC-01 (a task keeps a model whose own key is usable). The installed personal-key journey (`test_installed_personal_cli.py`) and the native per-developer key trial (`test_native_actor_provider_keys.py`) send tasks on a developer's own key, but they are optional and CI doesn't run them. The live own-key journey cases (DEV-09 and DEV-10, proposed) wait on the follow-up that gives the preview's fixture provider HTTPS, with a test certificate only the preview app trusts; once the journey suite declares them, they prove this row. |
| ST31 | My usage | DEV-04 (after tasks on a local and a cloud model, `keeplane usage` shows each model's tokens for today and this month, and the cloud model's estimated cost), USE-06, DU-01 | — |
| ST31 | A local model | DEV-04, PSI-LIVE-05 (on the default preview, the local model shows its tokens and "—" for cost), DU-C2, USE-06 | — |
| ST31 | Cost is an estimate | DEV-04 (the cloud model's cost is marked as an estimate and the table says "Costs are estimates from each provider's list price"), USE-06, DU-C1 | DEV-04's cloud model is added within the same hour it is used, so not all its tokens are priced and it may show the partly-priced note instead of a cost above zero. |
| ST31 | Only my own usage | DEV-04 (a second developer's task isn't in the first developer's totals), USE-09 (`keeplane usage` has no option for another developer), DU-02, DU-03, DU-04 | — |
