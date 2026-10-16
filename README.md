# Keeplane

Keeplane gives engineering teams one way to work with AI models through their
own network. The current development application includes sign-in, Users,
Models and routing, optional Data Classes and Audit. The developer CLI, smart
routing and project-class enforcement are still being built.

## Run locally

Install Python 3.9+, Node.js 22.12+ with npm, and Docker with Compose. Start
Docker, then run this from the repository root:

```sh
python3 deploy/local/up.py
```

Open the address printed by the command and sign in as `first-admin` using the
printed password-file location. Existing accounts and models are kept.

Use `--port 3080` to choose another port, or `--verbose` to see build output.
The [local setup guide](docs/guide/local-preview.md) covers prerequisites,
configuration, a short walkthrough, stopping and troubleshooting.

## Find your way around

| Directory | Contents |
| --- | --- |
| `components/admin-ui/` | React application and shared browser assets |
| `components/control-plane/` | Django API, accounts, model setup, classes and Audit |
| `components/cli/` | Experimental local coding-runtime adapter |
| `integrations/gateway/` | Gateway configuration |
| `deploy/` | Local development and Kubernetes packaging |
| `tests/` | Tests, fixtures, case descriptions and visual baselines |
| `docs/` | Setup, feature and operations guides |

See the [documentation index](docs/README.md), [architecture](docs/architecture/local-preview.md)
and [contribution guide](CONTRIBUTING.md). The local application is for development;
production installation and gateway-policy acceptance remain in progress.

Keeplane is licensed under [Apache 2.0](LICENSE). Bundled fonts retain their
[original license](components/admin-ui/public/fonts/LICENSE.txt).
