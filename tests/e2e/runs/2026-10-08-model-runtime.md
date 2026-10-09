# 2026-10-08 model runtime regression

The pinned Qwen2.5 Coder 0.5B GGUF ran in llama.cpp behind agentgateway
1.6.0. The same `test_model_runtime.py` probe ran inside the Keeplane app
container in Docker Compose and in the isolated kind cluster. Neither runner
nor gateway was exposed on a host port for this test.

| Case | Docker | kind | Evidence |
| --- | --- | --- | --- |
| LOCAL-19: read the active context, model training context and sampler defaults | Pass | Pass | [Docker JSON](2026-10-08-model-runtime-docker.json), [kind JSON](2026-10-08-model-runtime-kind.json) |
| LOCAL-20: observe the output cap directly and through agentgateway | Pass: both stopped at 256 tokens | Pass: both stopped at 256 tokens | Same JSON files |

The server's `/props` response reported `max_tokens: -1` while both measured
completion paths ended at 256 tokens with `finish_reason: length`. The
configured `-n 256` limit is effective in this pinned image. The test uses
`ignore_eos` to prevent a model-chosen early stop from hiding that limit; an
initial unsuppressed Docker attempt stopped at 190 tokens through the gateway
and therefore could not prove the cap. The test does not measure answer quality
or guarantee another model or runtime version behaves the same way.
