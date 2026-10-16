"""Optional package provenance is useful only when the original bytes match."""

import copy
import hashlib
import json
from zipfile import ZipFile

import collect_cli_auth_sources as inventory
import pytest


@pytest.fixture
def artifacts(tmp_path):
    cache = tmp_path / "cache"
    cache.mkdir()
    wheel = cache / "example-1.0-py3-none-any.whl"
    with ZipFile(wheel, "w") as archive:
        archive.writestr("example.dist-info/licenses/NOTICE", b"Original copyright\n")
    source = cache / "example-1.0.tar.gz"
    source.write_bytes(b"Retained opaque archive; never executed or extracted")
    digest = lambda data: hashlib.sha256(data).hexdigest()
    pins = {
        "packages": [
            {
                "name": "example",
                "version": "1.0",
                "wheel": {"file": wheel.name, "sha256": digest(wheel.read_bytes())},
                "source": {
                    "file": source.name,
                    "url": "https://example.test/source",
                    "sha256": digest(source.read_bytes()),
                },
                "notices": {
                    "example.dist-info/licenses/NOTICE": digest(b"Original copyright\n")
                },
            }
        ],
        "supplemental_license_texts": [],
        "open_native_review": ["Native source provenance remains open"],
    }
    return cache, pins, tmp_path / "output"


def test_offline_original_bytes_and_incomplete_native_review(artifacts):
    cache, pins, output = artifacts
    result = inventory.collect(pins, cache, output, source_cache=cache)
    assert result["artifacts_verified"] and result["original_notice_files"] == 1
    assert not result["complete_native_inventory"]
    assert not result["archives_extracted"] and not result["packages_installed"]
    assert (
        output / "notices/example/example.dist-info/licenses/NOTICE"
    ).read_bytes() == b"Original copyright\n"
    assert (output / "example/example-1.0.tar.gz").read_bytes() == (
        cache / "example-1.0.tar.gz"
    ).read_bytes()
    with pytest.raises(FileExistsError):
        inventory.collect(pins, cache, output, source_cache=cache)


def test_corrupt_wheel_refused_before_output(artifacts):
    cache, pins, output = artifacts
    (cache / pins["packages"][0]["wheel"]["file"]).write_bytes(b"Changed wheel")
    with pytest.raises(ValueError, match="Wheel checksum"):
        inventory.collect(pins, cache, output, source_cache=cache)
    assert not output.exists()


@pytest.mark.parametrize("path", ["../NOTICE", "/NOTICE", "a\\NOTICE", "."])
def test_notice_paths_cannot_escape_output(artifacts, path):
    cache, pins, output = artifacts
    pins["packages"][0]["notices"] = {path: "a" * 64}
    with pytest.raises(ValueError, match="Unsafe"):
        inventory.collect(pins, cache, output, source_cache=cache)
    assert not output.exists()


def test_corrupt_source_retains_failed_inventory(artifacts):
    cache, pins, output = artifacts
    (cache / pins["packages"][0]["source"]["file"]).write_bytes(b"Changed source")
    result = inventory.collect(pins, cache, output, source_cache=cache)
    assert not result["artifacts_verified"]
    assert json.loads((output / "inventory.json").read_text()) == result
    assert not (output / "example/example-1.0.tar.gz").exists()


def test_pinned_graph_matches_requirements_and_detects_drift():
    pins = json.loads((inventory.ROOT / "licenses/cli-auth-trial.json").read_text())
    requirements = (inventory.ROOT / "requirements-cli-auth.txt").read_text()
    inventory.check_requirements(pins, requirements)
    changed = copy.deepcopy(pins)
    changed["packages"][0] = changed["packages"][1]
    with pytest.raises(ValueError, match="inventory changed"):
        inventory.check_requirements(changed, requirements)
