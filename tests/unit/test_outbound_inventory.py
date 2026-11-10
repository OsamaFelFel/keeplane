"""Every outbound connection the server can open is declared (ADR 009).

Cases EGR-01 to EGR-07 in tests/unit/outbound-connection-cases.md. The
runtime cases (EGR-10 to EGR-14) are in
tests/integration/test_outbound_connections.py.
"""

import ast
import re
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from tests.support.outbound import (
    ADDRESS_LITERALS,
    CALL_SITE_USERS,
    CALL_SITES,
    CLI,
    CLI_ADDRESS_LITERALS,
    CLI_CALL_SITES,
    CLI_DESTINATIONS,
    DESTINATIONS,
    GUIDE,
    REPO,
    RUNTIME_GLOBAL_SETTINGS,
    RUNTIME_INHERITED,
    RUNTIME_PROVIDER_POLICIES,
    RUNTIME_PROVIDERS_OFF,
    RUNTIME_SEARCH_KEYS,
    RUNTIME_SETTINGS,
    RUNTIME_SWITCHES,
    RUNTIME_WEB_OFF,
    SERVER,
    address_literals,
    call_site_users,
    network_imports,
    scan,
)

CATALOG = REPO / "tests" / "unit" / "outbound-connection-cases.md"
REFERENCE = REPO / "docs" / "guide" / "kubernetes-installation-reference.md"

# Every pinned server dependency, reviewed for connections it opens on its own
# (telemetry, update checks, downloads). "none": no network code is reached
# from Keeplane's use. Anything else names how the path is closed.
REVIEWED_PACKAGES = {
    # requirements-account-api.txt (every app image)
    "django": "Database backends only (declared); mail would need django.core.mail, which no server module imports, and ADMINS/MANAGERS stay empty (EGR-05)",
    "djangorestframework": "none",
    "asgiref": "none",
    "sqlparse": "none",
    "gunicorn": "Listens only; no statsd host is configured (EGR-05)",
    "packaging": "none",
    # requirements-postgres.txt
    "psycopg": "The configured database only (declared)",
    # requirements-cli-auth.txt (optional sign-in trial)
    "certifi": "none (CA data)",
    "cffi": "Calls C functions, sockets included, only when imported; EGR-01 fails if a server module imports it",
    "charset-normalizer": "none",
    "cryptography": "none",
    "django-oauth-toolkit": "Token introspection is the only outbound feature; RESOURCE_SERVER_INTROSPECTION_URL stays unset (EGR-05)",
    "idna": "none",
    "jwcrypto": "none",
    "oauthlib": "none",
    "pycparser": "none",
    "requests": "HTTP client, only when imported; EGR-01 fails if a server module imports it",
    "typing-extensions": "none",
    "urllib3": "HTTP client, only when imported; EGR-01 fails if a server module imports it",
    # requirements-detection.txt (optional personal-data detection)
    "annotated-doc": "none",
    "annotated-types": "none",
    "anyio": "Opens connections only when called; EGR-01 fails if a server module imports it",
    "blis": "none",
    "catalogue": "none",
    "click": "click.launch opens a URL in a browser, only when called; EGR-01 fails if a server module reaches it",
    "cloudpathlib": "Cloud paths only when given one; the model is a local package. EGR-01 fails if a server module imports it",
    "confection": "none",
    "cymem": "none",
    "en-core-web-lg": "none (model data, installed in the image)",
    "filelock": "none",
    "h11": "HTTP protocol only, when imported; EGR-01 fails if a server module imports it",
    "httpcore": "HTTP transport, only when imported; EGR-01 fails if a server module imports it",
    "httpx": "HTTP client, only when imported; EGR-01 fails if a server module imports it",
    "jinja2": "none",
    "markdown-it-py": "none",
    "markupsafe": "none",
    "mdurl": "none",
    "murmurhash": "none",
    "numpy": "none",
    "phonenumbers": "none (metadata bundled)",
    "preshed": "none",
    "presidio-analyzer": "Downloads a missing spaCy model; Keeplane refuses a model that is not installed before Presidio loads (EGR-06)",
    "pydantic": "none",
    "pydantic-core": "none",
    "pygments": "none",
    "pyyaml": "none",
    "regex": "none",
    "requests-file": "none (file: URLs)",
    "rich": "none",
    "setuptools": "none",
    "shellingham": "none",
    "smart-open": "Remote paths only when given one; Keeplane gives none. EGR-01 fails if a server module imports it",
    "spacy": "spacy.cli.download only through Presidio's missing-model path, which Keeplane closes (EGR-06); EGR-01 fails if a server module reaches spacy.cli",
    "spacy-legacy": "none",
    "spacy-loggers": "none",
    "srsly": "none",
    "thinc": "none",
    "tldextract": "Fetches the public-suffix list by default; Keeplane uses the bundled copy (EGR-06), and personal_data/engine.py is its only declared importer (EGR-01)",
    "tqdm": "none",
    "typer": "typer.launch opens a URL in a browser, only when called; EGR-01 fails if a server module reaches it",
    "typing-inspection": "none",
    "wasabi": "none",
    "weasel": "Remote project storage only through its own CLI. EGR-01 fails if a server module imports it",
    "wrapt": "none",
}


def pinned_packages():
    names = set()
    for path in sorted(SERVER.glob("requirements-*.txt")):
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith(("#", "-")):
                continue
            match = re.match(r"([A-Za-z0-9_.-]+)", line)
            assert match, (path.name, line)
            names.add(match[1].lower().replace("_", "-"))
    return names


# EGR-01 Every server module that can open a connection, download something
# or start a process is declared with what it imports and which destinations
# it reaches, and so is every module that imports such a call site directly;
# a new call site, a new network module in a declared one, or a new direct
# user of a call site fails.
def test_egr_01_every_server_call_site_is_declared():
    imports, _, users = scan()
    declared = {name: mods for name, (mods, _, _) in CALL_SITES.items() if mods}
    assert imports == declared, (
        "Declare new outbound call sites in tests/support/outbound.py and "
        "docs/guide/outbound-connections.md"
    )
    assert users == CALL_SITE_USERS, (
        "Declare modules that import a call site in CALL_SITE_USERS"
    )
    # A call site with no network import of its own reaches its destinations
    # through another call site it imports.
    for name, (modules, dests, _) in CALL_SITES.items():
        if not modules:
            assert name in CALL_SITE_USERS, name
            reached = set().union(*(CALL_SITES[s][1] for s in CALL_SITE_USERS[name]))
            assert dests <= reached, name


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (
            "import importlib\nimportlib.import_module('requests.adapters')",
            {"requests"},
        ),
        ("__import__('smtplib')", {"smtplib"}),
        ("def f():\n    from urllib import request", {"urllib.request"}),
        ("from http.client import HTTPSConnection", {"http.client"}),
        ("from logging.handlers import HTTPHandler", {"logging.handlers"}),
        ("import urllib.request", {"urllib.request"}),
        ("import httpcore", {"httpcore"}),
        ("import h11", {"h11"}),
        ("import anyio", {"anyio"}),
        ("import tldextract", {"tldextract"}),
        ("from spacy.cli import download", {"spacy.cli"}),
        ("import spacy.cli", {"spacy.cli"}),
        ("import spacy\nspacy.cli.download('en_core_web_lg')", {"spacy.cli"}),
        ("from presidio_analyzer import AnalyzerEngine", {"presidio_analyzer"}),
        ("import smart_open", {"smart_open"}),
        ("from cloudpathlib import CloudPath", {"cloudpathlib"}),
        ("import weasel", {"weasel"}),
        ("import pip", {"pip"}),
        ("import ensurepip", {"ensurepip"}),
        ("import pty", {"pty"}),
        ("import urllib\nurllib.request.urlopen('x')", {"urllib.request"}),
        ("import http\nhttp.client.HTTPConnection('x')", {"http.client"}),
        ("import urllib as u\nu.request.urlopen('x')", {"urllib.request"}),
        ("import os\nos.system('curl x')", {"os.process"}),
        ("import os\nos.popen('wget x')", {"os.process"}),
        ("import os\nos.execvp('curl', ['curl'])", {"os.process"}),
        ("import os\nos.spawnlp(os.P_WAIT, 'curl', 'curl')", {"os.process"}),
        ("import os\nos.posix_spawnp('curl', ['curl'], {})", {"os.process"}),
        ("from os import system\nsystem('curl x')", {"os.process"}),
        ("import posix\nposix.system('curl x')", {"os.process"}),
        ("from posix import posix_spawn", {"os.process"}),
        ("import nt\nnt.spawnv(0, 'curl', ['curl'])", {"os.process"}),
        ("import _socket\n_socket.socket().connect(('x', 1))", {"_socket"}),
        ("from _socket import socket", {"_socket"}),
        ("import _ssl", {"_ssl"}),
        ("from urllib.robotparser import RobotFileParser", {"urllib.robotparser"}),
        (
            "import urllib\nurllib.robotparser.RobotFileParser('x').read()",
            {"urllib.robotparser"},
        ),
        ("from importlib import import_module as im\nim('socket')", {"socket"}),
        ("import importlib as il\nil.import_module('ssl')", {"ssl"}),
        ("import importlib\nimportlib.__import__('socket')", {"socket"}),
        ("import builtins\nbuiltins.__import__('smtplib')", {"smtplib"}),
        ("from builtins import __import__ as imp\nimp('ftplib')", {"ftplib"}),
        (
            "import importlib\nload = importlib.import_module\nload('socket')",
            {"socket"},
        ),
        (
            "from importlib import import_module as im\nget = im\nget('http.client')",
            {"http.client"},
        ),
        ("import importlib\nimportlib.import_module(name='socket')", {"socket"}),
        ("import webbrowser\nwebbrowser.open('https://x')", {"webbrowser"}),
        ("import _posixsubprocess", {"_posixsubprocess"}),
        ("from _winapi import CreateProcess", {"_winapi"}),
        ("import ctypes\nctypes.CDLL(None).connect", {"ctypes"}),
        ("from ctypes.util import find_library", {"ctypes"}),
        (
            (
                "from django.utils.module_loading import import_string\n"
                "import_string('socket.create_connection')"
            ),
            {"socket"},
        ),
        (
            (
                "from django.utils.module_loading import import_string as load\n"
                "load(dotted_path='smtplib.SMTP')"
            ),
            {"smtplib"},
        ),
        (
            (
                "from django.utils import module_loading\n"
                "module_loading.import_string('http.client.HTTPConnection')"
            ),
            {"http.client"},
        ),
        (
            "import pkgutil\npkgutil.resolve_name('socket:create_connection')",
            {"socket"},
        ),
        ("from pkgutil import resolve_name as rn\nrn('ssl:wrap_socket')", {"ssl"}),
        ("import pkgutil\nfind = pkgutil.resolve_name\nfind('ftplib')", {"ftplib"}),
        ("import runpy\nrunpy.run_module('pip')", {"pip"}),
        ("from runpy import run_module as rm\nrm(mod_name='ensurepip')", {"ensurepip"}),
        ("import runpy\nrunpy.run_path('tool.py')", {"runpy.run_path"}),
        ("from runpy import run_path", {"runpy.run_path"}),
        ("import xml.sax\nxml.sax.parse('doc.xml', None)", {"xml.sax"}),
        ("from xml.sax import make_parser", {"xml.sax"}),
        ("from xml.dom import pulldom", {"xml.dom.pulldom"}),
        ("import xml.dom.pulldom", {"xml.dom.pulldom"}),
        (
            "from multiprocessing.managers import BaseManager",
            {"multiprocessing.managers"},
        ),
        ("import _ctypes", {"_ctypes"}),
        ("from cffi import FFI", {"cffi"}),
        ("import click\nclick.launch('https://x')", {"click.launch"}),
        ("from click import launch", {"click.launch"}),
        ("from click.termui import launch", {"click.termui.launch"}),
        ("import typer\ntyper.launch('https://x')", {"typer.launch"}),
        ("from typer.main import launch", {"typer.main.launch"}),
        ("import click\nclick.echo('x')", set()),
        ("import runpy\nrunpy.run_module('json')", set()),
        ("from xml.dom import minidom", set()),
        ("from importlib import import_module as im\nim('json')", set()),
        ("from urllib.parse import urlsplit", set()),
        ("import os\nos.path.join('a', 'b')", set()),
        ("import urllib\nurllib.parse.quote('x')", set()),
    ],
)
def test_egr_01_the_scan_finds_hidden_and_indirect_call_sites(source, expected):
    assert network_imports(ast.parse(source)) == expected


def test_egr_01_importing_a_call_site_is_a_call_site():
    tree = ast.parse("from collect_runtime_sources import download")
    assert call_site_users(tree, "", "new.py") == {"collect_runtime_sources.py"}
    tree = ast.parse("from .adapter import AgentgatewayModelAdapter")
    assert call_site_users(tree, "integrations.gateway", "x.py") == {
        "integrations/gateway/adapter.py"
    }
    tree = ast.parse("from ..runners import local_runner")
    assert call_site_users(tree, "integrations.gateway", "x.py") == {
        "integrations/runners.py"
    }
    tree = ast.parse("import integrations.gateway.applied")
    assert call_site_users(tree, "", "x.py") == {"integrations/gateway/applied.py"}


# EGR-02 Every full address written in server code is declared, with the
# destination it belongs to, or as an address that is never contacted.
def test_egr_02_every_address_in_server_code_is_declared():
    _, addresses, _ = scan()
    found = set().union(*addresses.values())
    assert found == set(ADDRESS_LITERALS), (
        "Declare new addresses in tests/support/outbound.py and the guide"
    )
    assert {d for d in ADDRESS_LITERALS.values() if d} <= set(DESTINATIONS)


def test_egr_02_addresses_inside_longer_strings_are_found():
    tree = ast.parse(
        'CHECK = "Checking https://updates.example.com/v1/latest daily"\n'
        'url = f"https://telemetry.example.com/{name}"\n'
        'LOUD = "HTTPS://evil.example.com/"\n'
        'RAW = b"GET https://bytes.example.com/ping"'
    )
    assert address_literals(tree) == {
        "https://updates.example.com/v1/latest",
        "https://telemetry.example.com/",
        "HTTPS://evil.example.com/",
        "https://bytes.example.com/ping",
    }


# EGR-03 The declarations, the guide and the installation reference agree:
# every destination has a call site, every call site names known
# destinations, and the guide names each destination and is linked.
def test_egr_03_destinations_call_sites_and_guide_agree():
    used = set().union(*(dests for _, dests, _ in CALL_SITES.values()))
    assert used == set(DESTINATIONS)
    for name, (_, dests, why) in CALL_SITES.items():
        assert why, name
        when = {DESTINATIONS[d]["when"] for d in dests}
        # A build script never shares a module with a runtime connection.
        assert not ("build" in when and when - {"build"}), name
    guide = GUIDE.read_text()
    for name, destination in DESTINATIONS.items():
        assert destination["guide"] in guide, (name, destination["guide"])
    for phrase in (
        "no telemetry",
        "update check",
        "DNS",
        "HTTP_PROXY",
        "check_credentials",
        "tests/unit/outbound-connection-cases.md",
    ):
        assert phrase in guide, phrase
    reference = REFERENCE.read_text()
    section = reference.split("## Network policies", 1)[1].split("\n## ", 1)[0]
    assert "outbound-connections.md" in section
    # Provider-key checks and probes never use a proxy, so the reference must
    # say the app needs direct access rather than suggest a proxy is enough.
    assert "provider-key checks and Personal provider probes" in section
    assert "always connect directly" in section


# EGR-04 Every pinned server dependency has been reviewed for connections it
# opens on its own; a new or removed pin fails until the review is updated.
def test_egr_04_every_pinned_dependency_is_reviewed():
    assert pinned_packages() == set(REVIEWED_PACKAGES)
    assert all(note.strip() for note in REVIEWED_PACKAGES.values())


# EGR-05 Settings open no connection of their own: no network log handler,
# nobody to e-mail errors to, no token introspection URL, no statsd host.
def test_egr_05_settings_open_no_connection_of_their_own():
    from django.conf import settings

    handlers = settings.LOGGING.get("handlers", {}).values()
    assert {row["class"] for row in handlers} <= {
        "logging.NullHandler",
        "logging.StreamHandler",
    }
    assert list(settings.ADMINS) == [] and list(settings.MANAGERS) == []
    # Classes Django loads from settings by name: mail and cache stay local.
    # The real settings module, since the test runner swaps the mail backend.
    from config import settings as installed

    assert installed.EMAIL_BACKEND == "django.core.mail.backends.dummy.EmailBackend"
    assert {row["BACKEND"] for row in settings.CACHES.values()} <= {
        "django.core.cache.backends.locmem.LocMemCache",
        "django.core.cache.backends.dummy.DummyCache",
    }
    assert "RESOURCE_SERVER_INTROSPECTION_URL" not in settings.OAUTH2_PROVIDER
    assert "RESOURCE_SERVER_AUTH_TOKEN" not in settings.OAUTH2_PROVIDER
    gunicorn = (SERVER / "config" / "gunicorn.conf.py").read_text()
    assert "statsd" not in gunicorn


@pytest.fixture
def fake_detector(monkeypatch):
    """Stand-ins for spaCy, Presidio and tldextract that record their use."""
    calls = SimpleNamespace(installed=False, extractors=[], engines=[])

    spacy = ModuleType("spacy")
    spacy.util = SimpleNamespace(is_package=lambda name: calls.installed)
    tldextract = ModuleType("tldextract")

    def extractor(**options):
        calls.extractors.append(options)
        return lambda text: text

    tldextract.TLDExtract = extractor
    email = ModuleType(
        "presidio_analyzer.predefined_recognizers.generic.email_recognizer"
    )
    email.tldextract = tldextract

    class Provider:
        def __init__(self, nlp_configuration):
            calls.engines.append(nlp_configuration)

        def create_engine(self):
            return "nlp"

    class Analyzer:
        def __init__(self, nlp_engine, supported_languages):
            self.nlp_engine = nlp_engine

        def analyze(self, **_):
            return []

    presidio = ModuleType("presidio_analyzer")
    presidio.AnalyzerEngine = Analyzer
    nlp = ModuleType("presidio_analyzer.nlp_engine")
    nlp.NlpEngineProvider = Provider
    recognizers = ModuleType("presidio_analyzer.predefined_recognizers")
    generic = ModuleType("presidio_analyzer.predefined_recognizers.generic")
    generic.email_recognizer = email
    for name, module in {
        "spacy": spacy,
        "tldextract": tldextract,
        "presidio_analyzer": presidio,
        "presidio_analyzer.nlp_engine": nlp,
        "presidio_analyzer.predefined_recognizers": recognizers,
        "presidio_analyzer.predefined_recognizers.generic": generic,
        email.__name__: email,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)
    calls.email = email
    return calls


# EGR-06 The detector never reaches its download paths: a model that is not
# installed is refused before Presidio is asked to load it (Presidio would
# download it), and the email check reads tldextract's bundled list only.
def test_egr_06_a_missing_model_is_refused_before_presidio_loads(
    fake_detector, tmp_path
):
    from personal_data.engine import DetectorUnavailable, PresidioDetector

    with pytest.raises(DetectorUnavailable):
        PresidioDetector(str(tmp_path / "no-such-model"))
    assert fake_detector.engines == [] and fake_detector.extractors == []


def test_egr_06_the_email_check_uses_the_bundled_suffix_list(fake_detector):
    from personal_data.engine import PresidioDetector

    fake_detector.installed = True
    PresidioDetector("en_core_web_lg")
    assert fake_detector.extractors == [{"suffix_list_urls": (), "cache_dir": None}]
    assert fake_detector.email.tldextract.__name__ == "Offline"
    assert len(fake_detector.engines) == 1


# EGR-15 Every CLI module that can open a connection, start a process or open
# a browser is declared with what it imports and where it goes, and every
# address written in CLI code is declared; the CLI pins no package of its own.
def test_egr_15_every_cli_call_site_and_address_is_declared():
    imports, addresses, _ = scan(CLI)
    assert imports == {name: mods for name, (mods, _, _) in CLI_CALL_SITES.items()}, (
        "Declare new CLI call sites in tests/support/outbound.py and the guide"
    )
    assert set().union(*addresses.values()) == set(CLI_ADDRESS_LITERALS)
    used = set().union(*(dests for _, dests, _ in CLI_CALL_SITES.values()))
    assert used == set(CLI_DESTINATIONS)
    assert all(why for _, _, why in CLI_CALL_SITES.values())
    project = (REPO / "pyproject.toml").read_text()
    assert re.search(r"^dependencies = \[\]$", project, re.MULTILINE)


# EGR-16 The guide has a developer-computer section naming each CLI
# destination, the coding runtime's switches and the isolated-network rule.
def test_egr_16_the_guide_covers_developer_computers():
    guide = GUIDE.read_text()
    assert "## Developers' computers" in guide
    section = guide.split("## Developers' computers", 1)[1].split("\n## ", 1)[0]
    for destination in CLI_DESTINATIONS.values():
        assert destination["guide"] in section, destination["guide"]
    for phrase in (*RUNTIME_SWITCHES, "models.opencode.ai", "proxy",
                   "No web search and no web fetch"):
        assert phrase in section, phrase


def adapter_launch(tmp_path, monkeypatch, instructions=()):
    """Run the adapter with a stand-in runtime; return its environment and files."""
    import subprocess

    from components.cli import opencode_adapter

    seen = {}

    def version(command, **options):
        # The disposable settings folder exists only while the runtime runs.
        folder = Path(options["env"]["XDG_CONFIG_HOME"]) / "opencode"
        seen["global"] = {path.name: path.read_text() for path in folder.iterdir()}
        return subprocess.CompletedProcess(command, 0, "2.0.27", "")

    def turn(command, **options):
        seen["command"], seen["env"] = command, options["env"]
        return subprocess.CompletedProcess(command, 0, "", "")

    binary = tmp_path / "runtime"
    binary.touch()
    directory = tmp_path / "repository"
    directory.mkdir()
    (directory / "AGENTS.md").write_text("Use tabs.\n")
    for name in ("HTTP_PROXY", "https_proxy", "OPENCODE_MODELS_URL", "OPENAI_API_KEY",
                 "OPENCODE_CONFIG", "NO_PROXY", *RUNTIME_SEARCH_KEYS):
        monkeypatch.setenv(name, "https://outside.example.invalid")
    monkeypatch.setenv("OPENCODE_DISABLE_AUTOUPDATE", "0")
    monkeypatch.setattr(opencode_adapter.subprocess, "run", version)
    monkeypatch.setattr(opencode_adapter, "coding_turn", turn)
    opencode_adapter.run(
        str(binary), str(directory), "https://gateway.test/v1", "coder", "Fix it.",
        "synthetic-grant", instructions=[directory / name for name in instructions],
    )
    return seen


# EGR-17 The coding runtime `keeplane code` starts has its own outbound
# features off: no model catalogue download, no update check, no repository
# settings, no proxy or provider setting from the developer's shell, only the
# gateway as a provider, no MCP server or package to install, sharing off,
# web search and web fetch off, every built-in provider plugin (with the
# runtime's own sign-ins) off and every other provider denied, and the
# instruction plugin is a local folder with no dependency.
@pytest.mark.parametrize("instructions", [(), ("AGENTS.md",)])
def test_egr_17_the_coding_runtime_starts_with_its_own_connections_off(
    tmp_path, monkeypatch, instructions
):
    import json

    from components.cli import opencode_adapter

    seen = adapter_launch(tmp_path, monkeypatch, instructions)
    environment = seen["env"]
    for name, value in RUNTIME_SWITCHES.items():
        assert environment[name] == value, name
    profile = {"HOME", "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME",
               "XDG_STATE_HOME", "TMPDIR"}
    own = {"KEEPLANE_RUNTIME_GRANT", "OPENCODE_CONFIG_CONTENT", "OPENCODE_DISABLE_FFF"}
    assert set(environment) <= RUNTIME_INHERITED | profile | own | set(RUNTIME_SWITCHES)
    assert not {name for name in environment if "proxy" in name.lower()}
    assert json.loads(seen["global"]["opencode.json"]) == RUNTIME_GLOBAL_SETTINGS
    config = json.loads(environment["OPENCODE_CONFIG_CONTENT"])
    assert set(config) <= RUNTIME_SETTINGS
    assert config["share"] == "disabled"
    assert list(config["providers"]) == ["keeplane"]
    provider = config["providers"]["keeplane"]
    # Only the turn's loopback usage relay, which sends on to the gateway alone.
    assert opencode_adapter.relay_address(provider["settings"]["baseURL"])
    # A provider built into the runtime: nothing is installed for it.
    assert provider["package"] == "@opencode/ai/providers/openai-compatible"
    addresses = set(re.findall(r"[a-z][a-z0-9+.-]*://[^\s\"'<>]+", json.dumps(config)))
    assert addresses == {provider["settings"]["baseURL"]}
    assert seen["command"][1:4] == ["run", "--standalone", "--format"]
    # No web search or web fetch, even with search provider keys in the shell.
    assert config["websearch"] is False
    directives = [row for row in config["plugins"] if isinstance(row, str)]
    assert directives == list(RUNTIME_WEB_OFF) + list(RUNTIME_PROVIDERS_OFF)
    # No provider sign-in (D185): only the gateway provider may be used.
    assert config["experimental"] == {"policies": RUNTIME_PROVIDER_POLICIES}
    assert not set(RUNTIME_SEARCH_KEYS) & set(environment)
    plugins = [row for row in config["plugins"] if not isinstance(row, str)]
    assert len(plugins) == len(instructions)
    for plugin in plugins:
        folder = CLI / "instruction_plugin"
        assert plugin["package"] == str(folder.resolve())
        package = json.loads((folder / "package.json").read_text())
        assert not {key for key in package if "dependencies" in key.lower()}
        source = (folder / "index.js").read_text()
        imports = re.findall(r"""(?:from|import)\s*\(?\s*["']([^"']+)["']""", source)
        assert imports and all(name.startswith("node:") for name in imports)
        assert "node:http" not in imports and "node:net" not in imports
        assert not re.search(r"\bfetch\s*\(|child_process|XMLHttpRequest|WebSocket", source)


# EGR-07 Every case in the catalog has an executable check, and every check
# names a catalog case.
def test_egr_07_catalog_cases_link_to_checks():
    catalog = set(re.findall(r"^\| (EGR-\d\d) \|", CATALOG.read_text(), re.MULTILINE))
    tests = set()
    for path in (
        REPO / "tests" / "unit" / "test_outbound_inventory.py",
        REPO / "tests" / "integration" / "test_outbound_connections.py",
    ):
        tests |= {
            "EGR-" + number
            for number in re.findall(
                r"^def test_egr_(\d\d)_", path.read_text(), re.MULTILINE
            )
        }
    assert catalog == tests
