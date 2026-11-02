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
| EGR-01 | Read every Python file under `components/control-plane` for imports, at any depth, through `import_module` or `__import__`, or through a bare parent import (`import urllib` then `urllib.request.urlopen`), of a module that can open a connection, download something or start a process: sockets, TLS, HTTP clients and transports (including `httpcore`, `h11`, `anyio`), mail clients, database drivers, network log handlers, `subprocess`, `pty`, `pip`, `ensurepip`, `tldextract`, Presidio, `spacy.cli`, `smart_open`, `cloudpathlib`, `weasel`, and `os.system`, `os.popen`, `os.exec*`, `os.spawn*` and `os.posix_spawn*`. Also list every module that directly imports one of those call sites (relative imports resolved). | The modules and what each imports match the declared call sites exactly, and the direct users of call sites match their declaration; a call site with no network import of its own (such as `collect_cli_auth_sources.py`) reaches its destinations through one it imports. A new call site, a new network module in a declared one, or a new direct user fails and names the file. Each of the listed forms, written into a sample file, is found. |
| EGR-02 | Collect every full address (`scheme://…`) written in server code, including one inside a longer string or an f-string. | Each is declared with its destination, or as never contacted (the app's own default address, the CLI's loopback sign-in redirect, a parse-only placeholder). Anything new fails. |
| EGR-03 | Compare the declared destinations, call sites, the guide and the Kubernetes installation reference. | Every destination has a call site and every call site names known destinations; no build-time download shares a module with a runtime connection. The guide names each destination with its chart setting, says there is no telemetry or update check, covers DNS, proxies and `check_credentials`, and links this catalog; the reference's network policy section links the guide. |
| EGR-04 | List every package pinned in the server's `requirements-*.txt` files. | Each has a review note saying whether it can connect on its own and how that path is closed; a new or removed pin fails until the review is updated. |
| EGR-05 | Read the Django settings and the Gunicorn configuration. | Log handlers are only null or stream handlers; `ADMINS` and `MANAGERS` are empty, so no error is e-mailed; no OAuth token introspection URL is set; no statsd host is configured. |
| EGR-06 | Load the detector with stand-ins for spaCy, Presidio and tldextract, first with a model that is not installed, then with an installed one. | A missing model is refused before Presidio is asked to load it (Presidio would download it). With an installed model, Presidio's email check uses tldextract with no suffix-list URL and no cache, so the bundled list is read and nothing is fetched. |
| EGR-07 | Compare this catalog with the check names in both test files. | Every case here has a check named after it, and every check names a case here. |
| EGR-10 | Under the guard, call a declared loopback endpoint, then connect to `192.0.2.1:443`, to an undeclared loopback port and to an outside host name; send UDP datagrams with `sendto` (with and without flags) and `sendmsg` to outside addresses; reverse-look-up outside addresses with `gethostbyaddr` and `getnameinfo`; and look up an outside name with `gethostbyname`. | The declared call answers; every other attempt fails before a packet is sent, and each is recorded. The guard is removed afterwards. |
| EGR-11 | As an admin through the app's HTTP API, with a loopback test gateway and runner: read identity, list models, list a runner's models, add a runner model, list models again, read gateway status, `/health`, `/health/app`, `/health/ready`, data classes, projects and Audit options. | Every connection goes to the test gateway or runner, which both received calls; there is no other connection and no name lookup. |
| EGR-12 | Under the guard, call each runtime call site with loopback test endpoints: the gateway adapter, a listed gateway copy's read-back, a copy's applied configuration, runner discovery, the customer-run gateway preflight, the certificate check and the enroller's loopback admin read. | Each reaches only the address it was given (the enroller only `127.0.0.1:15000`); nothing else is contacted. |
| EGR-13 | Set `HTTP_PROXY` to a loopback test proxy, then read a copy's applied configuration, probe a Personal provider, run the provider-key check (the validator starts its worker with the approved provider address; only the read of the approved definition is stubbed), and in a new process call the gateway adapter and runner discovery. | The applied read, the probe and the key check go directly to their address (the key check sends the developer's key there) and the proxy sees nothing; the gateway and runner calls started with a proxy set go through it. |
| EGR-14 | Optional (`-m optional`, needs the detector and `en_core_web_lg`): under the guard, load the real detector and check a request with an email. | The email is found; there is no connection attempt and no name lookup. The image check DI-01 also loads it with no network. |

Not covered here:

- The guard sees the test's own Python process. The provider-key worker and
  the probe worker are separate processes: EGR-13 checks that each reaches
  only the provider address it is given and never a proxy, but not that it
  opens nothing else. The PostgreSQL client library (libpq) opens its own
  sockets and is not run here (the tests use SQLite). EGR-01 declares all
  three, and the chart's egress policies limit them in a cluster.
- EGR-01 lists direct users of a call site only. A module that reaches a
  call site through another module (for example a view using the gateway
  object from `common/api.py`) is not listed; the runtime checks EGR-11 and
  EGR-12 cover those paths.
- The scan reads Keeplane's own code. A library's own connections are
  covered by the dependency review (EGR-04), EGR-06 and EGR-14.
- An isolated-network install, a fresh node restart from internal images and
  developer computers are separate 002-03 checks.
