# Run Keeplane locally

From the Open Source repository root, with Docker running:

```sh
python3 deploy/local/up.py
```

Open [Keeplane](http://127.0.0.1:3000). The script starts one protected Docker
installation, including agentgateway 1.6.0 and a real Qwen2.5 Coder 0.5B
runner. It downloads and verifies the pinned Qwen file if needed. Repeating the
command keeps existing accounts, approvals, provider keys, and gateway models.
The runner is small enough for a CPU demo; its output is not a quality target
for the product.

The first admin is `first-admin`. Read the generated password on your own
machine with `cat /private/tmp/keeplane-accounts-trial/first-admin-password`.
The file is private and must stay out of Git. The app listens only on loopback.

## Five-minute walkthrough

1. Sign in at port 3000 and open **Models and routing**.
2. Choose **Add model** → **Local runner**. Enter `http://qwen:8080`, then
   choose **Find models**. Select `qwen2.5-coder:0.5b`.
3. Choose **Public** and **Internal** under **Approved for**, then add the
   model. If a prior run already added it, use **Set up** on its row to approve
   it. The row must show the approved classes.
4. Run `python3 tests/e2e/test_integrated_demo.py` to exercise the full
   journey and leave `demo-qwen` in the list. Then try your own prompt with
   `python3 deploy/local/ask.py demo-qwen 'Reply with READY.'`. The helper
   signs in, sends the request through agentgateway, and signs out; it is a
   developer demo tool, not the planned Keeplane CLI.
5. Choose **Sign out**. The admin model API should refuse a request made with
   that signed-out session.

The model field reports the runner's active context when available. This
preview uses 4,096 active tokens, while the underlying model reports a
32,768-token training context. The active limit constrains live requests.
Keeplane reads these values; it does not tune the model. The pinned runner
stops at 256 output tokens by default, as checked in `LOCAL-20`.

`local-fixture` returns a fixed `mock answer` for transport checks. The guarded
endpoint and cloud-provider containers are disposable integration fixtures;
neither is a production model or an external subscription. The supplied admin
UI has no separate chat or Try panel yet. API calls in the test runner use the
same session and model registration endpoints as the UI.

Run the full [plain-English regression](regression-local.md) with:

```sh
python3 tests/e2e/run_regression.py --output /private/tmp/keeplane-regression-new.json
```

For optional Qwen3 4B on the host, see the [Qwen3 guide](qwen3-local.md).
For Users and Editions, see [accounts](accounts-local.md). Stop containers with
`docker compose down`; omit `-v` to retain local data. This is a development
preview, not a Release 1 production installation.
