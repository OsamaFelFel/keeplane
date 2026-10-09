# 9 October 2026 — local runner context in Keeplane

The [plain-English case](../cases.md) LOCAL-24 checks that Add model shows the
running context of local Qwen separately from the model's training limit. The
same repeatable [runner-flow script](../test_runner_flow.py) ran against the
[Docker preview](2026-10-09-runner-context.json) and the
[kind preview](2026-10-09-runner-context-kind.json). Both runs passed all five
cases: discovery, 4,096 active and 32,768 training tokens, registration and a
generated answer, rejection of an unserved model, and rejection of a runner
address outside the preview allowlist.
An [isolated runner fixture](../test_runner_optional_context.py) with no
`/props` endpoint also passed [LOCAL-25](2026-10-09-runner-optional-context.json):
discovery returned its model and no invented context value.

I also opened Add model in the Docker browser preview, entered
`http://qwen:8080`, and selected Find models. The field displayed:
"Active context: 4,096 tokens. Model training context: 32,768 tokens."
The model dropdown and text field remained the same height, and I closed the
dialog without adding another model. The three preview endpoints recovered
after the app reload and kind rollout: Docker health 200, protected admin UI
302 to sign-in, and kind health 200.

This reads optional llama.cpp `/props` data. It does not infer an effective
limit from the GGUF training metadata, change the runner's settings, prove
another runner's context API, or make this 0.5B model suitable for coding
agents. The product canvas does not specify context presentation; the helper
text is a local preview diagnostic for product review.
