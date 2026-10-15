# Test Keeplane

Run Python tests from the repository root. Use Python 3.10 or newer for Django
and pytest; the local application launcher itself still supports Python 3.9.

```sh
python3 -m venv .venv
.venv/bin/pip install -r tests/requirements.txt
.venv/bin/python -m pytest
```

The default selection runs unit and integration checks without changing a live
application. Chart checks also require Helm 3.19 or newer on PATH, or
`KEEPLANE_HELM_BIN` pointing to Helm. Use `pytest tests/unit` for Python unit checks
only and `pytest --collect-only` to inspect the selected tests.

## Frontend and browser

In `components/admin-ui`, run `npm ci`, `npm run build`, `npm run lint` and
`npm run test:unit`. With Keeplane running, install and run browser tests:

```sh
cd tests/browser
npm ci
npx playwright install chromium --only-shell
npm test -- --workers=1
```

Set `KEEPLANE_BASE_URL` for another address and `KEEPLANE_RUNTIME_DIR` for another
credential directory. Failures retain traces and screenshot differences under
`test-results/browser`. Review a visible change before updating its baseline.

## Running applications and deployments

Start the [Docker application](local-preview.md) and [isolated Kubernetes
installation](kubernetes-local.md). Build the native PostgreSQL test image:

```sh
docker build --target postgres -t keeplane-preview:postgres-local -f components/control-plane/Dockerfile .
.venv/bin/python tests/run_regression.py --output test-results/full-regression.json
```

The full runner executes fast checks, disposable component fixtures, Docker and
kind journeys, deployment checks and both browser runs. Docker uses port 3000;
kind uses port 13000. NetworkPolicy/TLS deployment checks additionally require
the isolated Calico environment described by their case files. An unavailable
required environment is a failure or an explicitly unrun group.

Use a fresh output filename. JUnit reports, case reports, stdout and stderr are
retained beside it, including failures. The runner records the tested revision
and restores each preview's original data-class mode. `--group docker` or another
named group selects a partial run; it does not establish full regression.
The real-model output-limit check allows 600 seconds per reply and still
requires 256 generated tokens through both direct and gateway paths; it does
not measure response speed. Optional native Qwen3 trials are selected separately
with `pytest -m optional`.

## CI and evidence

PR checks run frontend checks, pytest unit/integration checks, documented Docker
startup on default and custom ports, Linux browser behavior and a disposable
PostgreSQL API/restore fixture. macOS visual baselines and full Kubernetes
acceptance have separate environments. Green CI covers only its selected checks.

Reports are retained as CI artifacts for 30 days, including failures. State the
tested revision, results and unrun checks in the PR. Release evidence needs a
longer retention policy. Commit fixtures, readable cases and deliberate visual
baselines; keep routine generated output outside source control.
