"""Every outbound connection the server can open is declared (ADR 009).

Cases EGR-01 to EGR-07 in tests/unit/outbound-connection-cases.md. The
runtime cases (EGR-10 to EGR-14) are in
tests/integration/test_outbound_connections.py.
"""

import re
import sys
from types import ModuleType, SimpleNamespace

import pytest

from tests.support.outbound import (
    ADDRESS_LITERALS,
    CALL_SITES,
    DESTINATIONS,
    GUIDE,
    REPO,
    SERVER,
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
    "requests": "HTTP client, only when imported; no server module imports it (EGR-01)",
    "typing-extensions": "none",
    "urllib3": "HTTP client, only when imported; no server module imports it (EGR-01)",
    # requirements-detection.txt (optional personal-data detection)
    "annotated-doc": "none",
    "annotated-types": "none",
    "anyio": "none",
    "blis": "none",
    "catalogue": "none",
    "click": "none",
    "cloudpathlib": "Cloud paths only when given one; the model is a local package",
    "confection": "none",
    "cymem": "none",
    "en-core-web-lg": "none (model data, installed in the image)",
    "filelock": "none",
    "h11": "none",
    "httpcore": "HTTP client, only when imported; no server module imports it (EGR-01)",
    "httpx": "HTTP client, only when imported; no server module imports it (EGR-01)",
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
    "smart-open": "Remote paths only when given one; Keeplane gives none",
    "spacy": "spacy.cli.download only through Presidio's missing-model path, which Keeplane closes (EGR-06)",
    "spacy-legacy": "none",
    "spacy-loggers": "none",
    "srsly": "none",
    "thinc": "none",
    "tldextract": "Fetches the public-suffix list by default; Keeplane uses the bundled copy (EGR-06)",
    "tqdm": "none",
    "typer": "none",
    "typing-inspection": "none",
    "wasabi": "none",
    "weasel": "Remote project storage only through its own CLI; not used",
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


# EGR-01 Every server module that can open a connection or start a process is
# declared with what it imports and which destinations it reaches; a new
# call site or a new network module in a declared one fails.
def test_egr_01_every_server_call_site_is_declared():
    imports, _ = scan()
    declared = {name: modules for name, (modules, _, _) in CALL_SITES.items()}
    assert imports == declared, (
        "Declare new outbound call sites in tests/support/outbound.py and "
        "docs/guide/outbound-connections.md"
    )


def test_egr_01_the_scan_finds_hidden_and_dynamic_imports():
    import ast

    tree = ast.parse(
        "def f():\n"
        "    import importlib\n"
        "    importlib.import_module('requests.adapters')\n"
        "    __import__('smtplib')\n"
        "    from urllib import request\n"
        "    from http.client import HTTPSConnection\n"
        "    from logging.handlers import HTTPHandler\n"
    )
    assert network_imports(tree) == {
        "requests",
        "smtplib",
        "urllib.request",
        "http.client",
        "logging.handlers",
    }
    assert network_imports(ast.parse("import urllib.request")) == {"urllib.request"}
    assert network_imports(ast.parse("from urllib.parse import urlsplit")) == set()


# EGR-02 Every full address written in server code is declared, with the
# destination it belongs to, or as an address that is never contacted.
def test_egr_02_every_address_in_server_code_is_declared():
    _, addresses = scan()
    found = set().union(*addresses.values())
    assert found == set(ADDRESS_LITERALS), (
        "Declare new addresses in tests/support/outbound.py and the guide"
    )
    assert {d for d in ADDRESS_LITERALS.values() if d} <= set(DESTINATIONS)


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
