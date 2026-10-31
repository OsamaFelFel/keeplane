"""The chart's gateway copy lists are ones the app accepts (no Helm needed).

The chart renders GATEWAY_COPY_URLS for the managed gateway and checks an
installer's list for an existing gateway with values.schema.json. Both must
agree with the app's own parser, or an install that Helm accepts would leave
every widening model change unconfirmed.
"""

import json
import re
from pathlib import Path

import pytest
from integrations.gateway.copies import (
    MAX_COPIES,
    GatewayCopiesUnavailable,
    copy_urls,
)

ROOT = Path(__file__).resolve().parents[2]
CHART = ROOT / "deploy/helm/keeplane"
SCHEMA = json.loads((CHART / "values.schema.json").read_text())
GATEWAY = SCHEMA["properties"]["gateway"]
COPY_LIST = GATEWAY["properties"]["copyUrls"]
ENTRY = re.compile(COPY_LIST["items"]["pattern"])

ACCEPTED = [
    "http://gateway-0.gateway:4000",
    "http://customer-gateway-1.customer-gateway.gateway.svc.cluster.local:4000",
    "https://10.0.0.7:8443",
    "https://gateway.example.test",
    "http://[fd00::7]:4000",
]
REFUSED = [
    "http://admin:secret@gateway-0.gateway:4000",
    "http://gateway-0.gateway:4000/api",
    "http://gateway-0.gateway:4000/",
    "http://gateway-0.gateway:4000?x=1",
    "http://gateway-0.gateway:4000#copy",
    "ftp://gateway-0.gateway:4000",
    "gateway-0.gateway:4000",
    "http://gateway 0:4000",
    "http://gateway-0.gateway:4000,http://gateway-1.gateway:4000",
    "http://",
    "",
]


def managed_list(release, count, namespace):
    """The list the chart's keeplane.gatewayCopyUrls helper renders."""
    return ",".join(
        f"http://{release}-gateway-{index}.{release}-gateway-copies.{namespace}.svc:4000"
        for index in range(count)
    )


@pytest.mark.parametrize("url", ACCEPTED)
def test_schema_accepts_only_entries_the_app_accepts(url):
    assert ENTRY.search(url)
    assert copy_urls(url) == [url]


@pytest.mark.parametrize("url", REFUSED)
def test_schema_refuses_entries_that_are_not_one_plain_origin(url):
    assert not ENTRY.search(url)


def test_schema_limits_match_the_app():
    assert COPY_LIST["maxItems"] == MAX_COPIES
    assert COPY_LIST["uniqueItems"] is True
    assert GATEWAY["properties"]["copies"] == {
        "type": "integer",
        "minimum": 1,
        "maximum": MAX_COPIES,
    }
    managed = next(
        rule["then"]["properties"]
        for rule in GATEWAY["allOf"]
        if rule["if"]["properties"]["mode"]["const"] == "managed"
    )
    assert managed["copyUrls"] == {"maxItems": 0}


@pytest.mark.parametrize("count", [1, 2, MAX_COPIES])
def test_managed_list_is_one_valid_address_per_copy(count):
    urls = copy_urls(managed_list("keeplane", count, "keeplane"))
    assert len(urls) == count
    assert (
        urls[0] == "http://keeplane-gateway-0.keeplane-gateway-copies.keeplane.svc:4000"
    )
    assert all(ENTRY.search(url) for url in urls)


def test_helper_renders_the_same_address_shape():
    helper = (CHART / "templates/_gateway.tpl").read_text()
    assert (
        '"http://%s-gateway-%d.%s-gateway-copies.%s.svc:4000" '
        "$.Release.Name $index $.Release.Name $.Release.Namespace" in helper
    )
    assert "until (int .Values.gateway.copies)" in helper


def test_one_bad_entry_still_refuses_the_whole_list_in_the_app():
    with pytest.raises(GatewayCopiesUnavailable):
        copy_urls(ACCEPTED[0] + "," + REFUSED[1])
