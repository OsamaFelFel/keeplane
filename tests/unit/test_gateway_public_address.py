"""The installer-set gateway address the server gives CLIs (Spec 009 ST30, ADR 030).

Cases GPA-01 to GPA-06 in gateway-public-address-cases.md.
"""

import pytest
from common.gateway_address import public_gateway_url

from components.cli import coding

ACCEPTED = [
    ("https://keeplane.example/v1", "https://keeplane.example/v1"),
    ("https://keeplane.example/v1/", "https://keeplane.example/v1"),
    ("https://Keeplane.Example:443/v1", "https://keeplane.example/v1"),
    ("https://keeplane.example:8443/v1", "https://keeplane.example:8443/v1"),
    ("https://[2001:db8::1]/v1", "https://[2001:db8::1]/v1"),
    ("http://127.0.0.1:5000/v1", "http://127.0.0.1:5000/v1"),
    ("http://localhost:5001/v1/", "http://localhost:5001/v1"),
    ("http://[::1]:5000/v1", "http://[::1]:5000/v1"),
]


# GPA-01
@pytest.mark.parametrize("value", [None, ""])
def test_an_unset_address_means_keeplane_does_not_know_it(value):
    assert public_gateway_url(value) is None


# GPA-02, GPA-03
@pytest.mark.parametrize(("value", "kept"), ACCEPTED)
def test_https_or_loopback_addresses_are_kept_in_the_cli_form(value, kept):
    assert public_gateway_url(value) == kept


# GPA-04
@pytest.mark.parametrize(
    "value",
    [
        "http://keeplane.example/v1",
        "http://10.0.0.5:5000/v1",
        "http://127.0.0.2:5000/v1",
    ],
)
def test_plain_http_to_another_computer_is_refused(value):
    with pytest.raises(
        RuntimeError, match="must use HTTPS unless the gateway is on this machine"
    ):
        public_gateway_url(value)


# GPA-05
@pytest.mark.parametrize(
    "value",
    [
        "https://keeplane.example",
        "https://keeplane.example/",
        "https://keeplane.example/v1/chat/completions",
        "https://keeplane.example/v2",
        "https://keeplane.example/api/v1",
        "https://keeplane.example/v1//",
        "https://keeplane.example/v1?team=a",
        "https://keeplane.example/v1?",
        "https://keeplane.example/v1#top",
        "https://user:secret@keeplane.example/v1",
        "https://user@keeplane.example/v1",
        "https://keeplane.example /v1",
        "https://keeplane.example/v1\n",
        "https://keeplane.example:99999/v1",
        "https://keeplane.example:0/v1",
        "https://keeplane.example:port/v1",
        "ftp://keeplane.example/v1",
        "keeplane.example/v1",
        "https:///v1",
        "https://ké.example/v1",
    ],
)
def test_anything_but_a_gateway_address_ending_in_v1_is_refused(value):
    with pytest.raises(RuntimeError, match="KEEPLANE_GATEWAY_PUBLIC_URL must be"):
        public_gateway_url(value)


# GPA-06
@pytest.mark.parametrize(("value", "kept"), ACCEPTED)
def test_the_cli_accepts_every_address_the_server_gives(value, kept):
    assert coding.gateway_endpoint(kept) == kept
