"""Every outbound connection the server can open is declared (ADR 009).

Cases EGR-01 to EGR-07 in tests/unit/outbound-connection-cases.md. The
runtime cases (EGR-10 to EGR-14) are in
tests/integration/test_outbound_connections.py.
"""

import ast
import re
import sys
from types import ModuleType, SimpleNamespace

import pytest

from tests.support.outbound import (
    ADDRESS_LITERALS,
    CALL_SITE_USERS,
    CALL_SITES,
    DESTINATIONS,
    GUIDE,
    REPO,
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
    "cffi": "none",
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
    "click": "none",
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
    "typer": "none",
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
