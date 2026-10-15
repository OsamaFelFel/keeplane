# Local development

- `up.py`: build and start the Docker application, migrate its Django database,
  and check sign-in and gateway readiness.
- `ask.py`: send a development model request through Keeplane.
- `run_qwen3.py`: start the optional native Qwen3/llama.cpp runner on the host.
- `kind-up.sh`: install the isolated Kubernetes integration environment.
- YAML files: local stack configuration and the model/provider/database services
  used by that environment.
- `prepare_volumes.py`: prepare private local files for the non-root container.
- `stack.lock.json`: exact component and demo-model versions.

Start with [Run locally](../../docs/guide/local-preview.md). General repository
maintenance tools belong in `scripts/` when needed. Test-only environments and
inputs belong in `tests/fixtures/`, with executable checks in the matching suite.
