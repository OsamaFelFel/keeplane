# Outbound connections from the server and developers' computers

**Edition:** Open Source; the same rule applies to Enterprise.
**Spec:** 002 Self-hosting, ST2 "Needs nothing from the internet" (ADR 009).

At runtime neither the Keeplane server nor the CLI on a developer's computer
has an undeclared outbound destination. The declared destinations, call
sites, addresses, reviewed dependencies and the coding runtime's switches are
in `tests/support/outbound.py`; the user-facing list is
[Outbound connections](../../docs/guide/outbound-connections.md). Adding a
connection means declaring it there, in the guide and, for a server runtime
destination, in the chart's egress settings.

EGR-01 to EGR-07 and EGR-15 to EGR-17 read the code
(`test_outbound_inventory.py`); EGR-10 to EGR-14 and EGR-18 run it under a
socket guard that refuses every connection and name lookup except declared
loopback test endpoints (`tests/integration/test_outbound_connections.py`).
Both run in the backend checks:
`pytest tests/unit/test_outbound_inventory.py tests/integration/test_outbound_connections.py`.

| ID | Plain-English check | Expected result |
| --- | --- | --- |
| EGR-01 | Read every Python file under `components/control-plane` for imports, at any depth, through a bare parent import (`import urllib` then `urllib.request.urlopen`), or through a call with a written module name to `__import__`, `importlib.import_module`, `importlib.__import__`, `builtins.__import__`, Django's `import_string`, `pkgutil.resolve_name` (`module:attribute`) or `runpy.run_module`, including under another name (`from importlib import import_module as im`, `load = importlib.import_module`), of a module that can open a connection, download something or start a process: sockets and TLS (including the low-level `_socket` and `_ssl`), `urllib.robotparser`, XML parsers that fetch external documents (`xml.sax`, `xml.dom.pulldom`), `webbrowser`, `click.launch`, `typer.launch`, HTTP clients and transports (including `httpcore`, `h11`, `anyio`), mail clients, database drivers, network log handlers, `multiprocessing.managers`, `subprocess` and its low-level `_posixsubprocess` and `_winapi`, `runpy.run_path`, `pty`, `ctypes`, `_ctypes`, `cffi`, `pip`, `ensurepip`, `tldextract`, Presidio, `spacy.cli`, `smart_open`, `cloudpathlib`, `weasel`, and `system`, `popen`, `exec*`, `spawn*` and `posix_spawn*` from `os`, `posix` or `nt`. Also list every module that directly imports one of those call sites (relative imports resolved). | The modules and what each imports match the declared call sites exactly, and the direct users of call sites match their declaration; a call site with no network import of its own (such as `collect_cli_auth_sources.py`) reaches its destinations through one it imports. A new call site, a new network module in a declared one, or a new direct user fails and names the file. Each of the listed forms, written into a sample file, is found. |
| EGR-02 | Collect every full address (`scheme://…`) written in server code, including one inside a longer string, an f-string or a bytes literal, in any letter case. | Each is declared with its destination, or as never contacted (the app's own default address, the CLI's loopback sign-in redirect, a parse-only placeholder). Anything new fails. |
| EGR-03 | Compare the declared destinations, call sites, the guide and the Kubernetes installation reference. | Every destination has a call site and every call site names known destinations; no build-time download shares a module with a runtime connection. The guide names each destination with its chart setting, says there is no telemetry or update check, covers DNS, proxies and `check_credentials`, and links this catalog; the reference's network policy section links the guide. |
| EGR-04 | List every package pinned in the server's `requirements-*.txt` files. | Each has a review note saying whether it can connect on its own and how that path is closed; a new or removed pin fails until the review is updated. |
| EGR-05 | Read the Django settings and the Gunicorn configuration. | Log handlers are only null or stream handlers; `ADMINS` and `MANAGERS` are empty, so no error is e-mailed; the installed settings use Django's dummy mail backend, so nothing can open an SMTP connection; every cache is a local-memory or dummy cache; no OAuth token introspection URL is set; no statsd host is configured. |
| EGR-06 | Load the detector with stand-ins for spaCy, Presidio and tldextract, first with a model that is not installed, then with an installed one. | A missing model is refused before Presidio is asked to load it (Presidio would download it). With an installed model, Presidio's email check uses tldextract with no suffix-list URL and no cache, so the bundled list is read and nothing is fetched. |
| EGR-07 | Compare this catalog with the check names in both test files. | Every case here has a check named after it, and every check names a case here. |
| EGR-10 | Under the guard, call a declared loopback endpoint, then connect to `192.0.2.1:443`, to an undeclared loopback port and to an outside host name; send UDP datagrams with `sendto` (with and without flags) and `sendmsg` to outside addresses; reverse-look-up outside addresses with `gethostbyaddr` and `getnameinfo`; and look up an outside name with `gethostbyname`. | The declared call answers; every other attempt fails before a packet is sent, and each is recorded. The guard is removed afterwards. |
| EGR-11 | As an admin through the app's HTTP API, with a loopback test gateway and runner: read identity, list models, list a runner's models, add a runner model, list models again, read gateway status, `/health`, `/health/app`, `/health/ready`, data classes, projects and Audit options. | Every connection goes to the test gateway or runner, which both received calls; there is no other connection and no name lookup. |
| EGR-12 | Under the guard, call each runtime call site with loopback test endpoints: the gateway adapter, a listed gateway copy's read-back, a copy's applied configuration, runner discovery, the customer-run gateway preflight, the certificate check and the enroller's loopback admin read. | Each reaches only the address it was given (the enroller only `127.0.0.1:15000`); nothing else is contacted. |
| EGR-13 | Set `HTTP_PROXY` to a loopback test proxy, then read a copy's applied configuration, probe a Personal provider, run the provider-key check (the validator starts its worker with the approved provider address; only the read of the approved definition is stubbed), and in a new process call the gateway adapter and runner discovery. | The applied read, the probe and the key check go directly to their address (the key check sends the developer's key there) and the proxy sees nothing; the gateway and runner calls started with a proxy set go through it. |
| EGR-14 | Optional (`-m optional`, needs the detector and `en_core_web_lg`): under the guard, load the real detector and check a request with an email. | The email is found; there is no connection attempt and no name lookup. The image check DI-01 also loads it with no network. |
| EGR-15 | Read every Python file under `components/cli` with the EGR-01 scan and collect every full address written there; read the CLI's package dependencies. | Each module that can connect, start a process or open a browser is declared with where it goes (the Keeplane server, the loopback sign-in listener, the browser, the coding runtime); the only address is the start of the loopback sign-in redirect; the CLI depends on no other package. Anything new fails. |
| EGR-16 | Read the guide's developer-computer section. | It names the server and gateway options, the loopback listener, the sign-in page, each switch the coding runtime gets, `models.opencode.ai`, proxies and the runtime's web search. |
| EGR-17 | Start a coding turn, with and without a reviewed instruction file, with a stand-in runtime and a developer's shell that sets a proxy, a provider key, a model catalogue address, a runtime settings file and `OPENCODE_DISABLE_AUTOUPDATE=0`. | The runtime gets the model catalogue, update and repository-settings switches on and an update policy of `disable`; it inherits only `PATH`, language and TLS certificate settings (no proxy, key or other runtime setting); its settings name only the gateway, as the one provider, through the built-in provider, with sharing off and no other key; the instruction plugin is the local folder, with no dependencies, importing only Node built-ins and making no request. |
| EGR-18 | Under the guard, with a loopback test server and a developer's shell that sets a proxy, run `keeplane whoami`, `keeplane models`, `keeplane code` (stand-in runtime) and `keeplane logout`. | Every connection goes to the test server; nothing else is contacted and no name is looked up; the runtime is started once without the proxy or the provider key. |

Not covered here:

- The guard sees the test's own Python process. The provider-key worker and
  the probe worker are separate processes: EGR-13 checks that each reaches
  only the provider address it is given and never a proxy, but not that it
  opens nothing else. The PostgreSQL client library (libpq) opens its own
  sockets and is not run here (the tests use SQLite). EGR-01 declares all
  three, and the chart's egress policies limit them in a cluster.
- The guard patches the `socket` module's Python functions. Code that uses
  the low-level `_socket` module, or calls the C library through `ctypes`,
  `_ctypes` or `cffi`, bypasses it (none can be patched from Python), and so
  would a compiled extension that opens its own sockets. EGR-01 is the only
  check for these and fails on any server module that imports one; compiled
  code in dependencies is covered by the dependency review (EGR-04).
- EGR-01 finds an import by string only when the module name is written in
  the call. A name built at runtime (`import_module(name)`), a name read
  from a variable or from settings, or an importer reached through `getattr`
  is not found; no server module imports by string today. Classes Django
  itself loads from settings by name (log handlers, mail backend, caches)
  are checked by EGR-05. `runpy.run_path` is flagged whatever file it runs. On
  the paths EGR-11 and EGR-12 run, the guard would still refuse such a
  module's connection if it went through `socket`.
- EGR-01 lists direct users of a call site only. A module that reaches a
  call site through another module (for example a view using the gateway
  object from `common/api.py`) is not listed; the runtime checks EGR-11 and
  EGR-12 cover those paths.
- The scan reads Keeplane's own code. A library's own connections are
  covered by the dependency review (EGR-04), EGR-06 and EGR-14.
- The coding runtime is a separate program. EGR-17 checks what Keeplane
  starts it with; the switches were read from the pinned runtime's own
  settings code, but the real runtime is not run here, so a connection it
  makes past those switches is not caught. The native runtime cases
  (`KEEPLANE_OPENCODE_V2_BIN`) start it with the same switches. Its web
  search and web fetch tools, used only when the model asks, are not turned
  off (see the guide).
- Browser and device sign-in are not run under the guard here; EGR-15
  declares their modules and the CLI sign-in cases cover their requests.
- An isolated-network install and a fresh node restart from internal images
  are separate 002-03 checks.
