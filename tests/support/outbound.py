"""Declared outbound connections of Keeplane, and a socket guard.

ADR 009: at runtime Keeplane has no undeclared outbound destination, on the
server or on a developer's computer. This module is the reviewed list that the
outbound checks compare the code with (cases in
tests/unit/outbound-connection-cases.md). Adding a connection means adding it
here, to docs/guide/outbound-connections.md and, for a server runtime
destination, to the chart's egress settings.
"""

import ast
import ipaddress
import os
import re
import socket
import urllib.request
from contextlib import contextmanager
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SERVER = REPO / "components" / "control-plane"
CLI = REPO / "components" / "cli"
GUIDE = REPO / "docs" / "guide" / "outbound-connections.md"

# Standard-library and third-party modules that can open a network connection,
# download something, or start a process that could. Importing any part of
# one, or reaching it through a bare parent import (`import urllib` then
# `urllib.request.urlopen`), is a call site. `ctypes`, `_ctypes` and `cffi`
# are listed because they can call the C library's socket and process
# functions directly, past every Python-level guard. `xml.sax` and
# `xml.dom.pulldom` fetch a document's external system IDs through urllib.
# `click.launch` and `typer.launch` open a URL in a browser. `runpy.run_path`
# runs a file the scan cannot follow, so it is reviewed as a call site.
NETWORK_MODULES = (
    "aiohttp",
    "anyio",
    "asyncio",
    "boto3",
    "botocore",
    "cffi",
    "click._termui_impl",
    "click.launch",
    "click.termui.launch",
    "cloudpathlib",
    "ctypes",
    "_ctypes",
    "django.core.mail",
    "django.db.backends.mysql",
    "django.db.backends.oracle",
    "django.db.backends.postgresql",
    "ensurepip",
    "ftplib",
    "grpc",
    "h11",
    "http.client",
    "httpcore",
    "httpx",
    "imaplib",
    "logging.handlers",
    "multiprocessing.connection",
    "multiprocessing.managers",
    "paramiko",
    "pip",
    "poplib",
    "_posixsubprocess",
    "presidio_analyzer",
    "psycopg",
    "psycopg2",
    "pty",
    "requests",
    "runpy.run_path",
    "smart_open",
    "smtplib",
    "_socket",
    "socket",
    "socketserver",
    "spacy.cli",
    "_ssl",
    "ssl",
    "subprocess",
    "telnetlib",
    "tldextract",
    "typer.launch",
    "typer.main.launch",
    "urllib.request",
    "urllib.robotparser",
    "urllib3",
    "weasel",
    "webbrowser",
    "websocket",
    "websockets",
    "_winapi",
    "xml.dom.pulldom",
    "xml.sax",
    "xmlrpc.client",
)

# Functions that import or run a module named by a string: `__import__`,
# `importlib.import_module`, `importlib.__import__`, `builtins.__import__`,
# Django's `import_string`, `pkgutil.resolve_name` (`module:attribute`) and
# `runpy.run_module`. Calls through these, or through a name bound to one
# (`from importlib import import_module as im`, `im = importlib.import_module`),
# count as imports. The value is the keyword that can carry the name.
IMPORTERS = {
    "__import__": "name",
    "import_module": "name",
    "import_string": "dotted_path",
    "resolve_name": "name",
    "run_module": "mod_name",
}
IMPORTER_MODULES = frozenset(
    {"builtins", "django.utils.module_loading", "importlib", "pkgutil", "runpy"}
)

# os (or posix/nt) functions that start another program; reported as
# "os.process".
OS_PROCESS = re.compile(
    r"(os|posix|nt)\.(system|popen|exec\w*|spawn\w*|posix_spawn\w*)"
)

# Where the server connects. "when" is runtime (a running installation),
# preview (the Docker preview only) or build (building an image or collecting
# source archives, never in a running installation). "guide" is text that
# docs/guide/outbound-connections.md must contain for this destination.
DESTINATIONS = {
    "database": {
        "when": "runtime",
        "what": "PostgreSQL: accounts, settings, approvals, Audit and guard status",
        "guide": "`egress.postgres`",
    },
    "gateway": {
        "when": "runtime",
        "what": "The model gateway and each listed gateway copy: model calls and management",
        "guide": "`egress.suppliedGateway`",
    },
    "gateway-loopback": {
        "when": "runtime",
        "what": "The model enroller's own gateway copy, inside that copy's Pod only",
        "guide": "`127.0.0.1:15000`",
    },
    "model-providers": {
        "when": "runtime",
        "what": "The provider address of a model an admin set up: key checks and provider probes",
        "guide": "`egress.modelEndpoints`",
    },
    "runners": {
        "when": "runtime",
        "what": "Local model runners the operator lists",
        "guide": "`egress.runners`",
    },
    "preview-runners": {
        "when": "preview",
        "what": "The Docker preview's fixed demo runner and guarded test provider",
        "guide": "`qwen:8080`",
    },
    "build-sources": {
        "when": "build",
        "what": "Pinned packages and source archives while an image is built or sources are collected",
        "guide": "build",
    },
}

# Every server module (relative to components/control-plane) that imports a
# network-capable module: what it imports and which destinations it reaches.
CALL_SITES = {
    "common/postgresql/base.py": (
        {"django.db.backends.postgresql"},
        {"database"},
        "Django's PostgreSQL backend: the app, migration Job and enroller connect here",
    ),
    "common/certificates.py": (
        {"socket", "ssl"},
        {"database", "gateway"},
        "check_credentials reads the certificate the database and an https gateway present",
    ),
    "common/credential_check.py": (
        {"ssl"},
        {"database", "gateway"},
        "check_credentials builds the trust used for those handshakes",
    ),
    "prepare_trust_bundle.py": (
        {"ssl"},
        set(),
        "Builds the app pods' CA bundle (trust.extraCaBundle); opens no connection",
    ),
    "integrations/gateway/adapter.py": (
        {"ssl", "urllib.request"},
        {"gateway", "gateway-loopback"},
        "Every model call and management request (GATEWAY_URL, GATEWAY_COPY_URLS)",
    ),
    "integrations/gateway/applied.py": (
        {"urllib.request"},
        {"gateway"},
        "Reads a gateway copy's applied configuration; never through a proxy",
    ),
    "integrations/gateway/preflight.py": (
        {"ssl", "urllib.request"},
        {"gateway"},
        "The customer-run gateway compatibility Job",
    ),
    "integrations/runners.py": (
        {"urllib.request"},
        {"runners"},
        "Runner discovery and its one-token answer check, only for listed runners",
    ),
    "model_registry/key_validation.py": (
        {"subprocess"},
        {"model-providers"},
        "Starts the provider-key worker with the approved provider address",
    ),
    "model_registry/provider_key_http.py": (
        {"urllib.request"},
        {"model-providers"},
        "The provider-key worker; never through a proxy, no redirects",
    ),
    "model_registry/provider_probe.py": (
        {"subprocess"},
        {"model-providers"},
        "Starts the no-key provider probe for a Personal model",
    ),
    "model_registry/provider_probe_http.py": (
        {"http.client", "urllib.request"},
        {"model-providers"},
        "The no-key provider probe; never through a proxy, no redirects",
    ),
    "model_registry/registration.py": (
        {"urllib.request"},
        {"preview-runners"},
        "Docker preview only: the demo runner's and guarded provider's health",
    ),
    "model_registry/runtime_installation.py": (
        {"urllib.request"},
        {"gateway-loopback"},
        "The enroller reads its own copy's admin port on loopback",
    ),
    "collect_runtime_sources.py": (
        {"urllib.request"},
        {"build-sources"},
        "Collects pinned source archives for the runtime image's notices",
    ),
    "package_postgres.py": (
        {"psycopg", "subprocess", "urllib.request"},
        {"build-sources"},
        "Image build: downloads the pinned PostgreSQL driver and its sources",
    ),
    "collect_cli_auth_sources.py": (
        set(),
        {"build-sources"},
        "Collects the sign-in trial's crates and workflow sources through collect_runtime_sources",
    ),
    "remove_runtime_installers.py": (
        {"subprocess"},
        set(),
        "Image build: uninstalls pip; connects nowhere",
    ),
    "personal_data/engine.py": (
        {"presidio_analyzer", "tldextract"},
        set(),
        "Loads the detector offline: no download, bundled suffix list (EGR-06)",
    ),
}

# Modules that import a declared call site directly, and which ones. The
# destinations are those of the call sites they import; a new direct user of
# a call site fails EGR-01 until it is listed here.
CALL_SITE_USERS = {
    "collect_cli_auth_sources.py": {"collect_runtime_sources.py"},
    "common/api.py": {"integrations/gateway/adapter.py"},
    "common/credential_check.py": {
        "common/certificates.py",
        "common/postgresql/base.py",
        "integrations/gateway/adapter.py",
    },
    "common/management/commands/check_credentials.py": {"common/credential_check.py"},
    "common/web.py": {"common/credential_check.py"},
    "integrations/gateway/copies.py": {"integrations/gateway/adapter.py"},
    "integrations/gateway/runtime_binding.py": {"integrations/gateway/applied.py"},
    "integrations/gateway/runtime_config.py": {"integrations/gateway/applied.py"},
    "model_registry/developer_keys.py": {"model_registry/key_validation.py"},
    "model_registry/installed_runtime.py": {"integrations/gateway/applied.py"},
    "model_registry/management/commands/install_runtime_guard.py": {
        "model_registry/runtime_installation.py"
    },
    "model_registry/management/commands/run_model_enroller.py": {
        "model_registry/runtime_installation.py"
    },
    "model_registry/model_enroller.py": {"model_registry/runtime_installation.py"},
    "model_registry/personal_dispatch.py": {"model_registry/key_validation.py"},
    "model_registry/registration.py": {
        "integrations/runners.py",
        "model_registry/provider_probe.py",
    },
    "model_registry/resolved_keys.py": {"model_registry/provider_key_http.py"},
    "model_registry/runtime_installation.py": {"integrations/gateway/applied.py"},
    "model_registry/runtime_keys.py": {"model_registry/key_validation.py"},
    "model_registry/use_cases.py": {"model_registry/registration.py"},
    "model_registry/views.py": {"integrations/runners.py"},
    "personal_data/inspection.py": {"personal_data/engine.py"},
}

# Every full address written in server code, and what it is.
ADDRESS_LITERALS = {
    "http://gateway:4000": "gateway",  # default GATEWAY_URL
    "http://127.0.0.1:4000": "gateway-loopback",  # the enroller's own copy
    "http://127.0.0.1:15000/config_dump": "gateway-loopback",
    "https://api.openai.com/v1": "model-providers",  # a definition without baseUrl
    "https://api.anthropic.com/v1": "model-providers",
    "http://qwen:8080": "preview-runners",  # default PREVIEW_RUNNER_URLS
    "http://qwen:8080/health": "preview-runners",
    "http://qwen:8080/v1": "preview-runners",
    "http://guarded-provider:18081/health": "preview-runners",
    "http://guarded-provider:18081/v1": "preview-runners",
    "http://model:18080/v1": "preview-runners",
    "https://distfiles.alpinelinux.org/distfiles/": "build-sources",
    "https://raw\\.githubusercontent\\.com/alpinelinux/aports/[a-f0-9]{40}/": "build-sources",
    "https://raw\\.githubusercontent\\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/[a-f0-9]{40}/\\.github/workflows/[A-Za-z0-9_.-]+\\.ya?ml": "build-sources",
    "https://static.crates.io/crates/": "build-sources",
    "registry+https://github.com/rust-lang/crates.io-index": "build-sources",
    "registry+https://github.com/rust-lang/crates.io-index#": "build-sources",
    # Not destinations: the app's own default address, the CLI's loopback
    # sign-in redirect on a developer's computer, and a parse-only placeholder.
    "http://127.0.0.1:3000": None,
    "http://127.0.0.1/callback": None,
    "https://provider.invalid": None,
}

# The Keeplane CLI on a developer's computer (components/cli). It connects
# only to addresses the developer gives it; it has no address of its own.
CLI_DESTINATIONS = {
    "keeplane-server": {
        "what": "The Keeplane server the developer signs in to: sign-in, refresh, account, projects, models, keys, sign-out",
        "guide": "`keeplane login --server`",
    },
    "sign-in-callback": {
        "what": "The CLI's own one-time listener on 127.0.0.1 for the browser sign-in redirect",
        "guide": "`127.0.0.1`",
    },
    "browser": {
        "what": "The developer's browser, opened on the server's sign-in page",
        "guide": "sign-in page",
    },
    "coding-runtime": {
        "what": "The coding runtime the developer installed, started by `keeplane code`; it reaches only the CLI's usage relay",
        "guide": "Coding runtime",
    },
    "usage-relay": {
        "what": "The CLI's own listener on 127.0.0.1 for one turn: the runtime's only provider address, sent on unchanged to the gateway (ADR 029)",
        "guide": "Usage relay",
    },
    "gateway": {
        "what": "The gateway URL the developer gave or the server saved at sign-in; only the usage relay connects to it",
        "guide": "`keeplane code --gateway`",
    },
}

# Every CLI module that imports a network-capable module: what it imports,
# which destinations it reaches, and why.
CLI_CALL_SITES = {
    "browser_login.py": (
        {"http.client", "socket", "ssl", "urllib.request", "webbrowser"},
        {"keeplane-server", "sign-in-callback", "browser"},
        "Browser sign-in: loopback callback listener, opens the server's sign-in page, exchanges the code; no proxy, no redirects (http.client and ssl only to tell a cut-off answer and a certificate problem from an outage)",
    ),
    "device_login.py": (
        {"urllib.request"},
        {"keeplane-server"},
        "Device-code sign-in against the server; no proxy, no redirects",
    ),
    "server_connection.py": (
        {"ssl", "urllib.request"},
        {"keeplane-server"},
        "Every signed-in request to the server; no proxy, no redirects (ssl only to tell a certificate problem from an outage)",
    ),
    "opencode_adapter.py": (
        {"subprocess"},
        {"coding-runtime"},
        "Starts the coding runtime with its own outbound features off and only the usage relay as a provider",
    ),
    "usage_relay.py": (
        {"http.client", "socket", "socketserver", "ssl"},
        {"usage-relay", "gateway"},
        "One turn's loopback relay: sends each runtime request unchanged to the gateway, adds no credential, reads each answer's usage; no proxy, no redirects",
    ),
    "keeplane.py": (
        {"subprocess"},
        set(),
        "Only catches the coding runtime's time-out; starts nothing itself",
    ),
}

# Every full address written in CLI code. None: never contacted as written.
CLI_ADDRESS_LITERALS = {
    "http://127.0.0.1:": None,  # start of the loopback sign-in redirect
}

# What `keeplane code` sets so the coding runtime (OpenCode V2 2.0.27) makes
# no connection of its own. Read from the runtime's settings code: the model
# catalogue download (models.opencode.ai), the update check and self-upgrade,
# and settings from the repository (which could add servers or plugins).
RUNTIME_SWITCHES = {
    "OPENCODE_DISABLE_MODELS_FETCH": "1",
    "OPENCODE_DISABLE_AUTOUPDATE": "1",
    "OPENCODE_CONFIG_PROJECT_DISABLE": "1",
}
# The update policy file the runtime reads from its (disposable) settings
# folder; it is also the policy the runtime checks when the switch is unset.
RUNTIME_GLOBAL_SETTINGS = {"update": "disable"}
# The only environment the runtime inherits from the developer's shell. Proxy
# settings, provider keys and every other OPENCODE_* setting are dropped.
RUNTIME_INHERITED = frozenset(
    {"PATH", "LANG", "LC_ALL", "SSL_CERT_FILE", "SSL_CERT_DIR"}
)
# The only settings keys `keeplane code` gives the runtime. Any other key (MCP
# servers, more providers, remote instructions, a catalogue address, packages
# to install) fails EGR-17 until it is reviewed.
RUNTIME_SETTINGS = frozenset(
    {"providers", "model", "share", "snapshots", "websearch", "plugins", "experimental"}
)
# Product decision (associate product owner, 2 November 2026): `keeplane code`
# has no web search or web fetch. In the runtime, `"websearch": false` turns
# search off, and a "-" plugin directive turns off a built-in plugin: the web
# fetch tool, the web search tool and each hosted search provider (Exa,
# Firecrawl, Parallel, Tavily, TinyFish), which work without a key.
RUNTIME_WEB_OFF = (
    "-opencode.tool.webfetch",
    "-opencode.tool.websearch",
    "-opencode.websearch.*",
)
# D185 (cloud models only through API keys): every built-in provider plugin
# is off. They add the runtime's own sign-ins (ChatGPT and OpenAI
# subscriptions, GitHub Copilot, GitLab and others, each with an OAuth
# listener), local-runner discovery (Ollama, LM Studio, vLLM on loopback
# ports) and package installs for other providers.
RUNTIME_PROVIDERS_OFF = ("-opencode.provider.*",)
# The runtime's provider policy: every provider is removed except the gateway,
# so the bundled catalogue's OpenAI, Anthropic and other providers can't be used.
RUNTIME_PROVIDER_POLICIES = [
    {"action": "provider.use", "resource": "*", "effect": "deny"},
    {"action": "provider.use", "resource": "keeplane", "effect": "allow"},
]
# Keys for hosted search providers that the runtime reads from its environment.
RUNTIME_SEARCH_KEYS = (
    "EXA_API_KEY",
    "FIRECRAWL_API_KEY",
    "PARALLEL_API_KEY",
    "TAVILY_API_KEY",
)

ADDRESS = re.compile(r"[a-z][a-z0-9+.-]*://[^\s\"'<>]+", re.IGNORECASE)


def server_files(root=SERVER):
    return sorted(root.rglob("*.py"))


def dotted(node):
    """'a.b.c' for an attribute chain rooted at a name, else None."""
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return None
    return ".".join([node.id, *reversed(parts)])


def importer_of(node, bound):
    """The importer a call target or assigned value refers to, or None."""
    if isinstance(node, ast.Name):
        return bound.get(node.id)
    if isinstance(node, ast.Attribute) and node.attr in IMPORTERS:
        return node.attr
    return None


def importer_names(tree):
    """Names in a parsed file bound to an importer, mapped to which one."""
    bound = {name: name for name in IMPORTERS}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module in IMPORTER_MODULES:
            bound |= {
                a.asname or a.name: a.name for a in node.names if a.name in IMPORTERS
            }
    # `im = importlib.import_module`, then possibly `load = im`: repeat until
    # no new name is bound.
    while True:
        new = {
            target.id: importer
            for node in ast.walk(tree)
            if isinstance(node, (ast.Assign, ast.AnnAssign, ast.NamedExpr))
            and node.value is not None
            and (importer := importer_of(node.value, bound))
            for target in (
                node.targets if isinstance(node, ast.Assign) else [node.target]
            )
            if isinstance(target, ast.Name) and target.id not in bound
        }
        if not new:
            return bound
        bound |= new


def imported_by(call, importer):
    """The module name an importer call names with a string literal, or None.

    The name is the first positional argument or the importer's keyword;
    `module:attribute` (pkgutil.resolve_name) is read as `module.attribute`.
    """
    if call.args:
        node = call.args[0]
    else:
        keyword = IMPORTERS[importer]
        node = next((k.value for k in call.keywords if k.arg == keyword), None)
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value.replace(":", ".")
    return None


def imported_names(tree, package=""):
    """Every module or module attribute a parsed file names through imports.

    Relative imports are resolved against `package`. A bare `import a` makes
    each attribute chain `a.b.c` used in the file count as a named import. A
    call with a string literal to an importer (see IMPORTERS), directly, as
    an attribute of any module, or through a name bound to it, counts too.
    """
    names, aliases = [], {}
    importers = importer_names(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.append(alias.name)
                aliases[alias.asname or alias.name.split(".", 1)[0]] = (
                    alias.name if alias.asname else alias.name.split(".", 1)[0]
                )
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                parts = package.split(".") if package else []
                parts = parts[: len(parts) - (node.level - 1)]
                base = ".".join([*parts, *([node.module] if node.module else [])])
            names += [base] + [f"{base}.{a.name}" for a in node.names]
        elif (
            isinstance(node, ast.Call)
            and (importer := importer_of(node.func, importers))
            and (target := imported_by(node, importer))
        ):
            names.append(target)
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and (chain := dotted(node)):
            root, _, rest = chain.partition(".")
            if root in aliases and rest:
                names.append(f"{aliases[root]}.{rest}")
    return names


def network_imports(tree, package=""):
    """The network-capable modules a parsed file reaches, at any depth."""
    found = set()
    for name in imported_names(tree, package):
        for module in NETWORK_MODULES:
            if name == module or name.startswith(module + "."):
                found.add(module)
        if OS_PROCESS.fullmatch(name):
            found.add("os.process")
    return found


def call_site_users(tree, package, own):
    """The declared call-site modules a parsed file imports directly."""
    modules = {site[:-3].replace("/", "."): site for site in CALL_SITES}
    return {
        modules[name]
        for name in imported_names(tree, package)
        if name in modules and modules[name] != own
    }


def address_literals(tree):
    """Addresses in str and bytes constants (bytes read as latin-1)."""
    texts = (
        node.value if isinstance(node.value, str) else node.value.decode("latin-1")
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, (str, bytes))
    )
    return {match[0] for text in texts for match in ADDRESS.finditer(text)}


def package_of(name):
    return name[:-3].replace("/", ".").rpartition(".")[0]


def scan(root=SERVER):
    """Module -> network imports, -> address literals, -> call sites it imports.

    `root` is the server (components/control-plane) by default, or the CLI
    (components/cli); call-site users are always the server's call sites.
    """
    imports, addresses, users = {}, {}, {}
    for path in server_files(root):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        name = path.relative_to(root).as_posix()
        package = package_of(name)
        if found := network_imports(tree, package):
            imports[name] = found
        if found := address_literals(tree):
            addresses[name] = found
        if found := call_site_users(tree, package, name):
            users[name] = found
    return imports, addresses, users


class OutboundRefused(OSError):
    """The guard refused a connection to an undeclared destination."""


PROXY_VARIABLES = (
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
)


class OutboundGuard:
    """Record every connection and name lookup; refuse all but declared loopback.

    `ports` are the loopback ports of the declared test endpoints. A
    connection or datagram (connect, connect_ex, sendto, sendmsg) to any
    other address or port, a name lookup for any host that is not a loopback
    name, and a reverse lookup of any address that is not loopback are
    recorded in `refused` and fail with OutboundRefused (or a lookup error)
    before a packet leaves the process.
    Unix sockets are local and allowed. The guard sees this Python process
    only: a worker process or the PostgreSQL client library (libpq) opens its
    own sockets.
    """

    LOOPBACK_NAMES = frozenset({"localhost", "127.0.0.1", "::1"})

    def __init__(self, ports=()):
        self.ports = set(ports)
        self.attempts, self.refused = [], []

    @classmethod
    def loopback(cls, host):
        if isinstance(host, bytes):
            host = host.decode("ascii", "replace")
        if host in cls.LOOPBACK_NAMES:
            return True
        try:
            return ipaddress.ip_address(str(host).split("%", 1)[0]).is_loopback
        except ValueError:
            return False

    def check_connect(self, family, address):
        if family == getattr(socket, "AF_UNIX", None):
            return
        host, port = address[0], address[1]
        self.attempts.append((host, port))
        if not (self.loopback(host) and port in self.ports):
            self.refused.append((host, port))
            raise OutboundRefused(f"Undeclared outbound connection to {host}:{port}")

    def check_lookup(self, host, port):
        if isinstance(host, bytes):
            host = host.decode("ascii", "replace")
        if host is None or self.loopback(host):
            return
        try:
            ipaddress.ip_address(host.split("%", 1)[0])
            return  # An address, not a name: the connection itself is checked.
        except ValueError:
            pass
        self.refused.append((host, port))
        raise socket.gaierror(socket.EAI_NONAME, f"Undeclared name lookup for {host}")

    def check_reverse(self, host):
        if isinstance(host, bytes):
            host = host.decode("ascii", "replace")
        if self.loopback(host):
            return
        self.refused.append((host, None))
        raise socket.herror(1, f"Undeclared reverse lookup for {host}")

    @contextmanager
    def active(self):
        guard = self
        original = {
            (socket.socket, name): getattr(socket.socket, name)
            for name in ("connect", "connect_ex", "sendto", "sendmsg")
        } | {
            (socket, name): getattr(socket, name)
            for name in (
                "getaddrinfo",
                "gethostbyname",
                "gethostbyname_ex",
                "gethostbyaddr",
                "getnameinfo",
            )
        }

        def call(owner, name, *args, **kwargs):
            return original[(owner, name)](*args, **kwargs)

        def guarded_connect(sock, address):
            guard.check_connect(sock.family, address)
            return call(socket.socket, "connect", sock, address)

        def guarded_connect_ex(sock, address):
            guard.check_connect(sock.family, address)
            return call(socket.socket, "connect_ex", sock, address)

        def guarded_sendto(sock, data, *rest):
            # sendto(data, address) or sendto(data, flags, address)
            guard.check_connect(sock.family, rest[-1])
            return call(socket.socket, "sendto", sock, data, *rest)

        def guarded_sendmsg(sock, buffers, *rest):
            # sendmsg(buffers[, ancdata[, flags[, address]]])
            if len(rest) >= 3 and rest[2] is not None:
                guard.check_connect(sock.family, rest[2])
            return call(socket.socket, "sendmsg", sock, buffers, *rest)

        def guarded_getaddrinfo(host, port, *args, **kwargs):
            guard.check_lookup(host, port)
            return call(socket, "getaddrinfo", host, port, *args, **kwargs)

        def guarded_gethostbyname(host):
            guard.check_lookup(host, None)
            return call(socket, "gethostbyname", host)

        def guarded_gethostbyname_ex(host):
            guard.check_lookup(host, None)
            return call(socket, "gethostbyname_ex", host)

        def guarded_gethostbyaddr(host):
            guard.check_reverse(host)
            return call(socket, "gethostbyaddr", host)

        def guarded_getnameinfo(address, flags):
            guard.check_reverse(address[0])
            return call(socket, "getnameinfo", address, flags)

        replacements = {
            (socket.socket, "connect"): guarded_connect,
            (socket.socket, "connect_ex"): guarded_connect_ex,
            (socket.socket, "sendto"): guarded_sendto,
            (socket.socket, "sendmsg"): guarded_sendmsg,
            (socket, "getaddrinfo"): guarded_getaddrinfo,
            (socket, "gethostbyname"): guarded_gethostbyname,
            (socket, "gethostbyname_ex"): guarded_gethostbyname_ex,
            (socket, "gethostbyaddr"): guarded_gethostbyaddr,
            (socket, "getnameinfo"): guarded_getnameinfo,
        }
        # The run's own proxy settings must not turn a loopback call into a
        # call to a proxy; which call sites use a proxy is checked separately.
        # urlopen keeps the proxies it first saw, so start a fresh opener too.
        environment = os.environ
        proxies = {
            name: environment.pop(name)
            for name in PROXY_VARIABLES
            if name in environment
        }
        opener = urllib.request._opener
        urllib.request._opener = None
        for (owner, name), value in replacements.items():
            setattr(owner, name, value)
        try:
            yield self
        finally:
            for (owner, name), value in original.items():
                setattr(owner, name, value)
            urllib.request._opener = opener
            environment.update(proxies)
