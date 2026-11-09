# Developer journey on the default preview

**Edition:** Open Source. Spec 009 as a whole, task 009-13, ADR 028, ADR 029,
ADR 030, and Spec 004 ST26 (DEV-03b). This is the developer half of the MVP
journey, DEV-01 to DEV-05 in order, with DEV-03b checked on DEV-03's task,
against `python3 deploy/local/up.py` started with no options. The admin half
is in [integrated-demo-cases.md](integrated-demo-cases.md). To try the
same steps by hand, see
[the local preview guide](../../docs/guide/local-preview.md#try-the-developer-half-by-hand).

Run with host port 14424 free and the pinned coding runtime, OpenCode V2
2.0.27 (the musl build the `coding-runtime` check downloads and hash-checks):

```sh
python3 deploy/local/up.py
KEEPLANE_OPENCODE_V2_BIN=/path/to/opencode \
  .venv/bin/python -m pytest tests/e2e/test_developer_journey.py -m live
```

The runtime is built for musl, so on most Linux machines it runs only in
Alpine; the live-preview workflow runs the suite there, on the host network,
after the other live gateway checks. Without `KEEPLANE_OPENCODE_V2_BIN`,
DEV-01, DEV-02 and DEV-05 still run, DEV-03, DEV-03b and DEV-04 are reported
as not run, and the suite is skipped. The workflow fails on any skipped case. The
suite also skips, with the reason, when the preview, its credentials, Docker,
the model enroller or that port are not available.

## Fixtures

- Two temporary developers, created by the first admin. Each has a private
  home folder, the default profile `~/.config/keeplane/account`, and the
  runtime on their `PATH` as `opencode`.
- The source-tree CLI (`components/cli/keeplane.py`). Its browser is a fixture
  that opens the URL the CLI gives it and uses Keeplane's real sign-in and
  consent pages.
- A sample repo: a new Git repo with `calc.py` (`return a - b`) and a failing
  `test_calc.py`, with a remote nobody has set up in Keeplane. The second
  developer has their own clone of the same remote, so it is the same project.
- A tool-capable fixture model, [`journey_coder.py`](../fixtures/journey_coder.py),
  on the host at the preview's allowed runner address
  `http://host.docker.internal:14424`. The admin adds it as a local model
  approved for Public data. When a request offers tools, it asks the runtime to
  read `calc.py`, then to edit `return a - b` to `return a + b`, then answers
  "The addition function is fixed." Each answer reports 10 input and 5 output
  tokens. It keeps the `temperature`, `top_p`, `max_tokens` and
  `max_completion_tokens` each request arrived with.
- The preview's fixture cloud model: the admin adds `gpt-5-mini` from OpenAI
  with the preview's shared fixture key, approved for Public data. The
  `cloud-provider` fixture answers "mock cloud answer" with 2 input and 3
  output tokens. `gpt-5-mini` has a row in the shipped price list.

The admin adds both models through the same API the **Add model** screen uses,
and the suite waits until the model enroller reports them enrolled. Afterwards
it signs both developers out, removes both models and both developers, and
waits for the enroller to settle. The project stays on **Projects**.

| ID | Plain-English action | Expected result |
| --- | --- | --- |
| DEV-01 | The developer runs `keeplane login --server http://127.0.0.1:3000`, signs in in the browser and allows the CLI, then runs `keeplane whoami`. | The CLI says `Signed in to Keeplane.` and `whoami` names the developer. |
| DEV-02 | In the sample repo, they run `keeplane models`, then `keeplane use` with the fixture model. | `models` exits 0 for the repo's own project (worked out from its remote), lists both new models, and lists only approved models: no model the admin's list shows as unapproved. `use` says `This repo's next tasks use <model>. Run `keeplane use --auto` to let Keeplane choose again.` |
| DEV-03 | They run `keeplane code "Make the failing test pass"`. | The sample test fails before. The runtime's requests reach the fixture model through the guarded gateway (at least 3 answers: read, edit, final answer). `calc.py` now says `return a + b`, it is the only changed file, and the test passes. The CLI shows the answer and the edit of `calc.py`, says `Using <model> for this task, as you chose with keeplane use.` and `Answered by <model>.` As the admin, **Projects** lists the repo under its remote path, not set up, with only that developer. |
| DEV-03b | Before DEV-03's task, the developer's CLI settings file holds `temperature` 0.37 and `max_tokens` 777 for the fixture model, in its `"models"` section (Spec 004 ST26, saved with `settings_file.set_request_settings`). | Every request of the DEV-03 task reaches the fixture model through the guarded gateway with `temperature` 0.37 and `max_tokens` 777, unchanged. Needs the CLI's `request_settings.py` (task 009-12, keeplane #257); until it is merged this case is reported as not run and the suite is skipped. |
| DEV-04 | The second developer signs in and runs one task on the fixture model in their clone. Then the first developer runs one task on the cloud model and runs `keeplane usage`. | Both tasks succeed; the cloud task's answer is shown and `Answered by <cloud model>.` The first developer's usage has exactly the two models they used. The fixture model's totals for today and this month are exactly 10 input and 5 output tokens per answer of the first developer's own DEV-03 task, with no requests missing tokens, so the second developer's task isn't in them; the second developer's own usage holds their task. The cloud model shows 2 input and 3 output tokens per request for today and this month, and a cost marked as an estimate: above zero, or, when the model was added within the same UTC hour (as here), not all its tokens are priced and `keeplane usage` says `<model>: some of its tokens couldn't be priced, so its cost may be low.` (ADR 029). In `keeplane usage`, the local model shows those tokens and `—` for cost, the cloud model shows a dollar cost, and the table says `Costs are estimates from each provider's list price (price list of …), in US dollars.` |
| DEV-05 | They run `keeplane logout`, then `keeplane code "anything"` and `keeplane models`. Then the old sign-in is sent straight to the guarded gateway. | `logout` exits 0. `code` and `models` each exit 1 with `You're signed out of Keeplane, so nothing was sent. Run keeplane login to sign in.` and print nothing else. The fixture model receives nothing, and the guarded gateway's log shows no new request while they run. The direct request with the old sign-in is refused (401 or 403), and the gateway's log shows exactly that one request, so the log count is known to work (task 009-05's sign-out check). |

DEV-06 to DEV-08 (device sign-in, an expired sign-in, the first admin coding)
aren't in this suite yet; device sign-in on the preview is checked by PSI-LIVE-02
in [preview-sign-in-live-cases.md](preview-sign-in-live-cases.md). A manual run with the bundled
local Qwen, which checks only that an answer comes back through the gateway, is
in [the local preview guide](../../docs/guide/local-preview.md#try-the-developer-half-by-hand).

The report, `developer-journey.json`, records each case's observations without
any credential, under `test-results/` (not kept in Git).
