# Outbound connections from the server

**Edition:** Open Source; the same rule applies to Enterprise.
**Spec:** 002 Self-hosting, ST2 "Needs nothing from the internet" (ADR 009).

At runtime the Keeplane server has no undeclared outbound destination. The
declared destinations, call sites, addresses and reviewed dependencies are in
`tests/support/outbound.py`; the user-facing list is
[Outbound connections](../../docs/guide/outbound-connections.md). Adding a
connection means declaring it there, in the guide and, for a runtime
destination, in the chart's egress settings.

EGR-01 to EGR-07 read the code (`test_outbound_inventory.py`); EGR-10 to
EGR-14 run it under a socket guard that refuses every connection and name
lookup except declared loopback test endpoints
(`tests/integration/test_outbound_connections.py`). Both run in the backend
checks: `pytest tests/unit/test_outbound_inventory.py tests/integration/test_outbound_connections.py`.

| ID | Plain-English check | Expected result |
| --- | --- | --- |
| EGR-01 | Read every Python file under `components/control-plane` for imports, at any depth and through `import_module` or `__import__`, of a module that can open a connection or start a process (sockets, TLS, HTTP and mail clients, database drivers, network log handlers, `subprocess`). | The modules and what each imports match the declared call sites exactly; a new call site, or a new network module in a declared one, fails and names the file. |
| EGR-02 | Collect every full address (`scheme://…`) written in server code. | Each is declared with its destination, or as never contacted (the app's own default address, the CLI's loopback sign-in redirect, a parse-only placeholder). Anything new fails. |
| EGR-03 | Compare the declared destinations, call sites, the guide and the Kubernetes installation reference. | Every destination has a call site and every call site names known destinations; no build-time download shares a module with a runtime connection. The guide names each destination with its chart setting, says there is no telemetry or update check, covers DNS, proxies and `check_credentials`, and links this catalog; the reference's network policy section links the guide. |
| EGR-04 | List every package pinned in the server's `requirements-*.txt` files. | Each has a review note saying whether it can connect on its own and how that path is closed; a new or removed pin fails until the review is updated. |
| EGR-05 | Read the Django settings and the Gunicorn configuration. | Log handlers are only null or stream handlers; `ADMINS` and `MANAGERS` are empty, so no error is e-mailed; no OAuth token introspection URL is set; no statsd host is configured. |
| EGR-06 | Load the detector with stand-ins for spaCy, Presidio and tldextract, first with a model that is not installed, then with an installed one. | A missing model is refused before Presidio is asked to load it (Presidio would download it). With an installed model, Presidio's email check uses tldextract with no suffix-list URL and no cache, so the bundled list is read and nothing is fetched. |
| EGR-07 | Compare this catalog with the check names in both test files. | Every case here has a check named after it, and every check names a case here. |
| EGR-10 | Under the guard, call a declared loopback endpoint, then connect to `192.0.2.1:443`, to an undeclared loopback port and to an outside host name. | The declared call answers; the others fail before connecting, and each is recorded. The guard is removed afterwards. |
| EGR-11 | As an admin through the app's HTTP API, with a loopback test gateway and runner: read identity, list models, list a runner's models, add a runner model, list models again, read gateway status, `/health`, `/health/app`, `/health/ready`, data classes, projects and Audit options. | Every connection goes to the test gateway or runner, which both received calls; there is no other connection and no name lookup. |
| EGR-12 | Under the guard, call each runtime call site with loopback test endpoints: the gateway adapter, a listed gateway copy's read-back, a copy's applied configuration, runner discovery, the customer-run gateway preflight, the certificate check and the enroller's loopback admin read. | Each reaches only the address it was given (the enroller only `127.0.0.1:15000`); nothing else is contacted. |
| EGR-13 | Set `HTTP_PROXY` to a loopback test proxy, then read a copy's applied configuration, probe a Personal provider (a separate worker process), and in a new process call the gateway adapter and runner discovery. | The applied read and the provider probe go directly to their address and the proxy sees nothing; the gateway and runner calls started with a proxy set go through it. |
| EGR-14 | Optional (`-m optional`, needs the detector and `en_core_web_lg`): under the guard, load the real detector and check a request with an email. | The email is found; there is no connection attempt and no name lookup. The image check DI-01 also loads it with no network. |

Not covered here: the guard sees the test's own Python process. The
provider-key and probe workers and the PostgreSQL client library (libpq) open
their own sockets; EGR-01 declares them, EGR-13 checks the workers reach only
their address, and the chart's egress policies limit them in a cluster. An
isolated-network install, a fresh node restart from internal images and
developer computers are separate 002-03 checks.
