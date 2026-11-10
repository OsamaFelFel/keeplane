# Protected Docker demo cases

These cases are the admin half of the MVP journey. The developer half, DEV-01
to DEV-05 (sign in from the CLI, choose a model, code in a sample repo, see
usage, sign out), is in [developer-journey-cases.md](developer-journey-cases.md).

Run `python3 deploy/local/up.py`, then `.venv/bin/python -m pytest tests/e2e/test_integrated_demo.py -m live`.
The test uses the same protected port 3000 API that the supplied admin screen
uses. Data classes are off on a fresh installation, so the admin turns them
on first. It leaves data classes on and `demo-qwen` approved for Public and
Internal data, ready for a human walkthrough. Its observation
report is [versioned here](https://github.com/OsamaFelFel/keeplane/blob/de0aba5f8052fbbec55a2060309812812f09588e/tests/e2e/runs/2026-10-09-integrated-demo.json).

| ID | Plain-English action | Expected result |
| --- | --- | --- |
| DEMO-01 | Open Keeplane without a session, then sign in as the generated first admin. | The model API refuses the anonymous request, the sign-in screen appears, and the admin reaches the Models and routing screen. |
| DEMO-02 | Inspect the Models and routing screen. | Add model and data-class approval controls are present. |
| DEMO-03 | Turn data classes on, then list them and find models at the local Qwen runner. | Data classes are on, Public and Internal are available, and the runner reports `qwen2.5-coder:0.5b`. |
| DEMO-04 | Add the local Qwen model as `demo-qwen` and approve Public and Internal data. | Keeplane checks the live route, registers it through the gateway, and shows both approvals. A repeat run recognizes the existing registration and restores approval and both data classes if needed. |
| DEMO-05 | Ask `demo-qwen` to reply with READY. | A generated answer comes through Keeplane and agentgateway; it is not the fixed fixture answer. |
| DEMO-06 | Sign out, then call the model API with the same browser session. | The API returns HTTP 401. |

This is a live local integration check. It does not verify provider quality,
external model subscriptions, production security, or keyboard and visual UI
behavior. The [manual walkthrough](../../docs/guide/local-preview.md) covers
the supplied screen controls.
