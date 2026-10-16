"""Optional package provenance is useful only when the original bytes match."""

import copy
import hashlib
import io
import json
import tarfile
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
    assert not result["archive_trees_unpacked"] and not result["packages_installed"]
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


@pytest.fixture
def native_artifacts(artifacts):
    cache, pins, output = artifacts
    original = b"Original native licence\n"
    source = cache / "native-2.0.tar.gz"
    with tarfile.open(source, "w:gz") as archive:
        member = tarfile.TarInfo("native-2.0/LICENSE")
        member.size = len(original)
        archive.addfile(member, io.BytesIO(original))
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    record = json.dumps(
        {
            "components": [
                {
                    "name": "native",
                    "version": "2.0",
                    "hashes": [{"alg": "SHA-256", "content": digest}],
                    "externalReferences": [
                        {"type": "distribution", "url": "https://example.test/native"}
                    ],
                }
            ]
        }
    ).encode()
    filename = "example.dist-info/sboms/native.json"
    package = pins["packages"][0]
    wheel = cache / package["wheel"]["file"]
    with ZipFile(wheel, "a") as archive:
        archive.writestr(filename, record)
    package["wheel"]["sha256"] = hashlib.sha256(wheel.read_bytes()).hexdigest()
    package["build_records"] = {filename: hashlib.sha256(record).hexdigest()}
    pins["native_sources"] = [
        {
            "name": "native",
            "version": "2.0",
            "source": {
                "file": source.name,
                "url": "https://example.test/native",
                "sha256": digest,
            },
            "declared_by": {"package": "example", "member": filename},
            "source_notices": {
                "native-2.0/LICENSE": hashlib.sha256(original).hexdigest()
            },
        }
    ]
    return cache, pins, output


def test_original_sbom_and_native_source_licence_are_preserved(native_artifacts):
    cache, pins, output = native_artifacts
    result = inventory.collect(pins, cache, output, source_cache=cache)
    assert result["artifacts_verified"] and result["original_build_records"] == 1
    assert (
        result["source_notice_files"] == 1 and not result["complete_native_inventory"]
    )
    assert (
        output / "notices/native/native-2.0/LICENSE"
    ).read_bytes() == b"Original native licence\n"
    assert (
        output / "build-records/example/example.dist-info/sboms/native.json"
    ).is_file()


@pytest.mark.parametrize("changed", ["url", "sha256", "version"])
def test_native_source_must_match_the_verified_wheel_record(native_artifacts, changed):
    cache, pins, output = native_artifacts
    native = pins["native_sources"][0]
    if changed == "version":
        native["version"] = "2.1"
    else:
        native["source"][changed] = (
            "https://example.test/other" if changed == "url" else "a" * 64
        )
    with pytest.raises(ValueError, match="does not match the wheel SBOM"):
        inventory.collect(pins, cache, output, source_cache=cache)
    assert not output.exists()


def test_wrong_native_notice_leaves_failed_inventory(native_artifacts):
    cache, pins, output = native_artifacts
    pins["native_sources"][0]["source_notices"]["native-2.0/LICENSE"] = "a" * 64
    result = inventory.collect(pins, cache, output, source_cache=cache)
    assert not result["artifacts_verified"] and result["source_notice_files"] == 0
    assert result["native_notice_failures"] == [
        {"component": "native", "error_class": "ValueError"}
    ]
    assert not (output / "notices/native").exists()


def test_native_archive_notice_symlink_is_never_followed(native_artifacts):
    cache, pins, output = native_artifacts
    native = pins["native_sources"][0]
    source = cache / native["source"]["file"]
    outside = cache / "outside-license"
    outside.write_bytes(b"Never copy this target")
    with tarfile.open(source, "w:gz") as archive:
        member = tarfile.TarInfo("native-2.0/LICENSE")
        member.type, member.linkname = tarfile.SYMTYPE, str(outside)
        archive.addfile(member)
    native["source"]["sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
    package = pins["packages"][0]
    wheel = cache / package["wheel"]["file"]
    with ZipFile(wheel) as archive:
        records = {name: archive.read(name) for name in archive.namelist()}
    name = native["declared_by"]["member"]
    record = json.loads(records[name])
    record["components"][0]["hashes"][0]["content"] = native["source"]["sha256"]
    records[name] = json.dumps(record).encode()
    with ZipFile(wheel, "w") as archive:
        for filename, data in records.items():
            archive.writestr(filename, data)
    package["wheel"]["sha256"] = hashlib.sha256(wheel.read_bytes()).hexdigest()
    package["build_records"][name] = hashlib.sha256(records[name]).hexdigest()
    result = inventory.collect(pins, cache, output, source_cache=cache)
    assert not result["artifacts_verified"] and result["source_notice_files"] == 0
    assert not (output / "notices/native").exists()
    assert outside.read_bytes() == b"Never copy this target"
