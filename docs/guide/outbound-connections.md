# Outbound connections

Keeplane needs nothing from the internet to run. This page lists every
connection the Keeplane server opens, and when, so that an installation on an
isolated network can open exactly those destinations and nothing else. It
covers the app, its install Jobs and the model enroller. Developers' computers
(the CLI) and the web UI in the browser are covered separately; the web UI
loads everything from Keeplane itself.

There is no telemetry, no update check, no licence check, no hosted font or
CDN, and no outside control plane. The optional personal-data detector loads
its language model from the image and never downloads a model or a list.

```mermaid
flowchart LR
  subgraph cluster["Your network"]
    app["App<br/>(each copy)"]
    jobs["Install Jobs<br/>migration, preflight"]
    subgraph copy["Each managed gateway copy (Pod)"]
      enroller["Model enroller"]
      gw["Gateway<br/>4000, admin 15000"]
    end
    db[("PostgreSQL")]
    runner["Local model runners"]
    supplied["Customer-run gateway<br/>(existing mode)"]
    dns["Cluster DNS"]
  end
  provider["Model providers<br/>(only those you set up)"]
  app -- "model calls, management" --> gw
  app -- "existing mode" --> supplied
  app --> db
  app -- "Personal models: key checks, probes" --> provider
  app -- "discovery, when an admin adds one" --> runner
  jobs --> db
  jobs -- "preflight" --> supplied
  enroller -- "loopback only" --> gw
  enroller --> db
  gw -- "registered models" --> provider
  gw -- "registered models" --> runner
  app & jobs & enroller -.-> dns
```

## What each part connects to

| From | To | When | Chart setting with `networkPolicy.egressEnabled` |
| --- | --- | --- | --- |
| App | Cluster DNS | To find any name below | `networkPolicy.dns` |
| App | PostgreSQL | Every request that reads or writes accounts, settings, approvals or Audit (PostgreSQL mode) | `egress.postgres` |
| App | The managed gateway Service and each copy on TCP 4000 | Every model call, model change and copy read-back; `/health` and the admin status page | Allowed by the app egress policy in managed mode |
| App | A customer-run gateway (`gateway.url` and every `gateway.copyUrls`) | The same calls, in existing mode | `egress.suppliedGateway` |
| App | The provider address of a Personal model an admin set up | When an admin sets the model up (a probe without any key) and when a developer saves or rechecks their own key for it | `egress.modelEndpoints` |
| App | A runner listed in `app.runnerUrls` | Only when an admin lists a runner's models or adds a runner model | `egress.runners` |
| Migration Job | PostgreSQL | Before install and upgrade | `egress.postgres` |
| Preflight Job (existing mode) | The customer-run gateway | Before install and upgrade | `egress.suppliedGateway` |
| Model enroller | Its own gateway copy at `127.0.0.1:4000` and the copy's admin port `127.0.0.1:15000` | Every few seconds; both stay inside the copy's Pod | None needed: loopback |
| Model enroller | PostgreSQL (read-only approvals and its own guard-status row) | Every few seconds | `egress.postgres`, added to the gateway egress policy |
| `check_credentials` (run in an app Pod) | The database server and an `https` gateway address | When you run it: it reads the certificate each one presents | Same as the app |

The managed gateway copies themselves connect to the registered model
providers and runners (`egress.modelEndpoints`), the gateway database in
database mode (`egress.gatewayDatabase`) and, with the model enroller, the app
on TCP 3000. See [network policies](kubernetes-installation-reference.md#network-policies)
for the policies that enforce all of this.

A provider address comes only from a model an admin set up. A definition
without its own address uses the provider's public address,
`https://api.openai.com/v1` or `https://api.anthropic.com/v1`; give a
`baseUrl` to keep that call inside your network.

## Proxies

Keeplane uses an HTTP proxy only where noted:

- The provider-key check, the Personal provider probe and the read of a gateway
  copy's applied configuration never use a proxy, and never follow a redirect.
  On an isolated network the app must reach those providers directly, so list
  them in `egress.modelEndpoints` even when the gateway copies reach them
  through a proxy.
- Calls to the gateway and runner discovery use `HTTP_PROXY`, `HTTPS_PROXY`
  and `NO_PROXY` if they are set in the app's environment when it starts. The
  chart sets none of them. If you add one, put your gateway and runner hosts
  in `NO_PROXY`.

## The Docker preview

The Docker preview on a developer's computer also checks its fixed demo
runner (`qwen:8080`) and guarded test provider (`guarded-provider:18081`)
inside its own Docker network. Its first start downloads images, packages and
the demo model; see [Run locally](local-preview.md).

## Install and build

Images are built, and source archives for the licence notices are collected,
before installation. Those steps download pinned packages and sources and are
never run by a running installation. Pulling images is the only install-time
need: make the pinned images available inside your network before you close
any temporary registry access (see [Images](kubernetes-installation-reference.md#images)).

## How this is checked

The [outbound connection cases](../../tests/unit/outbound-connection-cases.md)
fail the backend checks when server code gains a connection, an address or a
dependency that is not declared here, and run an admin journey and each call
site against local test endpoints with every other connection refused.
