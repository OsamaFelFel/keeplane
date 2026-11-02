"""Declared outbound connections of the Keeplane server, and a socket guard.

ADR 009: at runtime Keeplane has no undeclared outbound destination. This
module is the reviewed list that the outbound checks compare the code with
(cases in tests/unit/outbound-connection-cases.md). Adding a connection means
adding it here, to docs/guide/outbound-connections.md and, for a runtime
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
GUIDE = REPO / "docs" / "guide" / "outbound-connections.md"

# Standard-library and third-party modules that can open a network connection
# or start a process that could. Importing any part of one is a call site.
NETWORK_MODULES = (
    "aiohttp",
    "asyncio",
    "boto3",
    "botocore",
    "django.core.mail",
    "django.db.backends.mysql",
    "django.db.backends.oracle",
    "django.db.backends.postgresql",
    "ftplib",
    "grpc",
    "http.client",
    "httpx",
    "imaplib",
    "logging.handlers",
    "multiprocessing.connection",
    "paramiko",
    "poplib",
    "psycopg",
    "psycopg2",
    "requests",
    "smtplib",
    "socket",
    "socketserver",
    "ssl",
    "subprocess",
    "telnetlib",
    "urllib.request",
    "urllib3",
    "websocket",
    "websockets",
    "xmlrpc.client",
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
    "remove_runtime_installers.py": (
        {"subprocess"},
        set(),
        "Image build: uninstalls pip; connects nowhere",
    ),
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

ADDRESS = re.compile(r"[a-z][a-z0-9+.-]*://\S+")


def server_files():
    return sorted(SERVER.rglob("*.py"))


def network_imports(tree):
    """The network-capable modules a parsed file imports, at any depth."""
    found = set()
    for node in ast.walk(tree):
        names = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            names = [node.module] + [f"{node.module}.{a.name}" for a in node.names]
        elif (
            isinstance(node, ast.Call)
            and (
                (
                    isinstance(node.func, ast.Name)
                    and node.func.id in ("__import__", "import_module")
                )
                or (
                    isinstance(node.func, ast.Attribute)
                    and node.func.attr == "import_module"
                )
            )
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            names = [node.args[0].value]
        for name in names:
            for module in NETWORK_MODULES:
                if name == module or name.startswith(module + "."):
                    found.add(module)
    return found


def address_literals(tree):
    return {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and ADDRESS.fullmatch(node.value)
    }


def scan():
    """(module -> network imports, module -> address literals) for server code."""
    imports, addresses = {}, {}
    for path in server_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        name = path.relative_to(SERVER).as_posix()
        if found := network_imports(tree):
            imports[name] = found
        if found := address_literals(tree):
            addresses[name] = found
    return imports, addresses


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
    connection to any other address or port, and a name lookup for any host
    that is not a loopback name, is recorded in `refused` and fails with
    OutboundRefused (or a lookup error) before a packet leaves the process.
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

    @contextmanager
    def active(self):
        guard = self
        saved = {
            (socket.socket, "connect"): socket.socket.connect,
            (socket.socket, "connect_ex"): socket.socket.connect_ex,
            (socket, "getaddrinfo"): socket.getaddrinfo,
            (socket, "gethostbyname"): socket.gethostbyname,
            (socket, "gethostbyname_ex"): socket.gethostbyname_ex,
        }
        connect = saved[(socket.socket, "connect")]
        connect_ex = saved[(socket.socket, "connect_ex")]
        getaddrinfo = saved[(socket, "getaddrinfo")]
        gethostbyname = saved[(socket, "gethostbyname")]
        gethostbyname_ex = saved[(socket, "gethostbyname_ex")]

        def guarded_connect(sock, address):
            guard.check_connect(sock.family, address)
            return connect(sock, address)

        def guarded_connect_ex(sock, address):
            guard.check_connect(sock.family, address)
            return connect_ex(sock, address)

        def guarded_getaddrinfo(host, port, *args, **kwargs):
            guard.check_lookup(host, port)
            return getaddrinfo(host, port, *args, **kwargs)

        def guarded_gethostbyname(host):
            guard.check_lookup(host, None)
            return gethostbyname(host)

        def guarded_gethostbyname_ex(host):
            guard.check_lookup(host, None)
            return gethostbyname_ex(host)

        replacements = {
            (socket.socket, "connect"): guarded_connect,
            (socket.socket, "connect_ex"): guarded_connect_ex,
            (socket, "getaddrinfo"): guarded_getaddrinfo,
            (socket, "gethostbyname"): guarded_gethostbyname,
            (socket, "gethostbyname_ex"): guarded_gethostbyname_ex,
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
            for (owner, name), value in saved.items():
                setattr(owner, name, value)
            urllib.request._opener = opener
            environment.update(proxies)
