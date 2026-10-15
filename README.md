# Keeplane

Keeplane gives teams one way to work with AI models through their own network.
This repository currently contains a **protected local Docker preview of model
registration and transport**, not a Release 1 installation.

## Run locally

From this directory:

```sh
python3 deploy/local/up.py
```

Open [Keeplane locally](http://127.0.0.1:3000) and sign in as `first-admin`.
The startup command prints the location of its private password file and keeps
existing local data. Follow the [five-minute walkthrough](docs/guide/local-preview.md)
to add a real Qwen model, optionally approve data classes, send a request, and sign out.
The [integrated E2E](tests/e2e/integrated-demo-cases.md) verifies that journey.

For the optional Qwen3 4B host runner, see its
[local setup guide](docs/guide/qwen3-local.md).
The guarded endpoint remains an automated credential-forwarding test fixture;
it is not offered in the Add model dialog.

For a Kubernetes integration trial with the official agentgateway Helm chart,
two gateway replicas, and an app-only existing-gateway mode, see the
[local Kubernetes guide](docs/guide/kubernetes-local.md).
The [gateway configuration guide](docs/guide/gateway-configuration.md) explains
managed and customer-supplied gateway modes and their current trial limits.
For admin sign-in, Users and Editions, see the
[account guide](docs/guide/accounts-local.md).
The same protected preview has a [model approval trial](docs/guide/model-approval-local.md):
gateway models get no Keeplane work until an admin sets them up.
The [Add model guide](docs/guide/model-add-local.md) covers the protected
OpenAI and Anthropic format trial through a local authenticated mock.
The [data-class trial](docs/guide/data-classes-local.md) starts off on a new
installation; admins can opt in, then change starter classes and approvals.
The [Audit guide](docs/guide/audit-local.md) covers the React screen and the
mandatory break-glass sign-in records in the protected Docker preview.

## What this preview covers

- Keeplane's own Models and routing screen, based on the product design canvas.
- IBM Plex fonts and UI assets served locally, with their
  [font license notice](components/admin-ui/fonts/LICENSE.txt).
- A small control plane that registers a local model through agentgateway's API.
- One gateway and a deterministic test model, both on the private Docker network.
- A guarded endpoint fixture for testing gateway registration and credential
  forwarding to a real local Qwen runner.
- Versioned [plain English cases](tests/e2e/cases.md) and executable checks.

The port 3000 Docker preview requires admin sign-in. Project data-class enforcement,
complexity routing, the coding agent CLI and production identity installation
are still open. The UI binds only to `127.0.0.1`. See
[architecture](docs/architecture/local-preview.md).

## Stop

`docker compose down` stops the containers and keeps gateway data. Add `-v` only
if you want to erase locally registered models.
