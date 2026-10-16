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
def recipe_artifacts(artifacts):
    cache, pins, output = artifacts
    original = b"Original libffi notice\n"
    source = cache / "libffi-3.4.6.tar.gz"
    with tarfile.open(source, "w:gz") as archive:
        member = tarfile.TarInfo("libffi-3.4.6/LICENSE")
        member.size = len(original)
        archive.addfile(member, io.BytesIO(original))
    url = "https://github.com/libffi/libffi/archive/v3.4.6.tar.gz"
    recipe = cache / "release-workflow.yaml"
    recipe.write_text("build:\n  run: curl " + url + "\n")
    package = pins["packages"][0]
    pins["recipe_declared_sources"] = [
        {
            "name": "libffi",
            "version": "3.4.6",
            "attribution": "release-recipe-only",
            "wheel_build_attested": False,
            "declared_by": {
                "package": package["name"],
                "version": package["version"],
                "wheel_sha256": package["wheel"]["sha256"],
                "recipe": {
                    "file": recipe.name,
                    "url": "https://raw.githubusercontent.com/example/project/"
                    + "a" * 40
                    + "/.github/workflows/ci.yaml",
                    "sha256": hashlib.sha256(recipe.read_bytes()).hexdigest(),
                },
            },
            "source": {
                "file": source.name,
                "url": url,
                "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            },
            "source_notices": {
                "libffi-3.4.6/LICENSE": hashlib.sha256(original).hexdigest()
            },
        }
    ]
    return cache, pins, output


def test_recipe_originals_are_preserved_without_attesting_wheel_equivalence(
    recipe_artifacts,
):
    cache, pins, output = recipe_artifacts
    result = inventory.collect(pins, cache, output, source_cache=cache)
    assert result["artifacts_verified"] and result["recipe_source_notice_files"] == 1
    assert result["recipe_declared_source_records"] == pins["recipe_declared_sources"]
    assert not result["recipe_declared_source_records"][0]["wheel_build_attested"]
    assert (
        not result["complete_native_inventory"] and not result["archive_trees_unpacked"]
    )
    assert (
        output / "notices/recipe-libffi/libffi-3.4.6/LICENSE"
    ).read_bytes() == b"Original libffi notice\n"
    assert (output / "recipe-libffi/release-workflow.yaml").read_bytes() == (
        cache / "release-workflow.yaml"
    ).read_bytes()


@pytest.mark.parametrize("artifact", ["recipe", "source"])
def test_corrupt_recipe_or_source_retains_failed_report_without_notices(
    recipe_artifacts, artifact
):
    cache, pins, output = recipe_artifacts
    row = pins["recipe_declared_sources"][0]
    record = row["declared_by"]["recipe"] if artifact == "recipe" else row["source"]
    (cache / record["file"]).write_bytes(b"Changed bytes")
    result = inventory.collect(pins, cache, output, source_cache=cache)
    assert (
        not result["artifacts_verified"] and result["recipe_source_notice_files"] == 0
    )
    assert not (output / "notices/recipe-libffi").exists()
    assert json.loads((output / "inventory.json").read_text()) == result


@pytest.mark.parametrize(
    "mutation",
    [
        "package-version",
        "component-version",
        "wheel-subject",
        "mutable-recipe",
        "attestation",
        "duplicate",
        "unsafe-notice",
    ],
)
def test_recipe_attribution_drift_is_refused_before_output(recipe_artifacts, mutation):
    cache, pins, output = recipe_artifacts
    row = pins["recipe_declared_sources"][0]
    if mutation == "package-version":
        row["declared_by"]["version"] = "other"
    elif mutation == "component-version":
        row["version"] = "4.0.0"
    elif mutation == "wheel-subject":
        row["declared_by"]["wheel_sha256"] = "f" * 64
    elif mutation == "mutable-recipe":
        row["declared_by"]["recipe"]["url"] = row["declared_by"]["recipe"][
            "url"
        ].replace("a" * 40, "main")
    elif mutation == "attestation":
        row["wheel_build_attested"] = True
    elif mutation == "duplicate":
        pins["recipe_declared_sources"].append(copy.deepcopy(row))
    else:
        row["source_notices"] = {"../LICENSE": "a" * 64}
    with pytest.raises(ValueError):
        inventory.collect(pins, cache, output, source_cache=cache)
    assert not output.exists()


@pytest.mark.parametrize("occurrences", [0, 2])
def test_recipe_must_declare_the_exact_source_url_once(recipe_artifacts, occurrences):
    cache, pins, output = recipe_artifacts
    row = pins["recipe_declared_sources"][0]
    record = row["declared_by"]["recipe"]
    raw = (row["source"]["url"] + "\n").encode() * occurrences
    (cache / record["file"]).write_bytes(raw)
    record["sha256"] = hashlib.sha256(raw).hexdigest()
    result = inventory.collect(pins, cache, output, source_cache=cache)
    assert (
        not result["artifacts_verified"] and result["recipe_source_notice_files"] == 0
    )
    assert result["native_notice_failures"] == [
        {"component": "recipe-libffi", "error_class": "ValueError"}
    ]


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


@pytest.fixture
def rust_artifacts(artifacts):
    cache, pins, output = artifacts
    digest = lambda data: hashlib.sha256(data).hexdigest()
    components, crates = [], []
    lock = 'version = 3\n[[package]]\nname = "wrapper"\nversion = "0.1.0"\n[[package]]\nname = "local"\nversion = "0.1.0"\n'
    for name, scope in (("one", "required"), ("two", "excluded")):
        path = cache / (name + "-1.0.crate")
        with tarfile.open(path, "w:gz") as archive:
            for member_name, data in (
                ("LICENSE", b"Original crate copyright\n"),
                (
                    "Cargo.toml",
                    f'[package]\nname = "{name}"\nversion = "1.0"\nlicense = "MIT/Apache-2.0"\n'.encode(),
                ),
            ):
                member = tarfile.TarInfo(name + "-1.0/" + member_name)
                member.size = len(data)
                archive.addfile(member, io.BytesIO(data))
        sha = digest(path.read_bytes())
        components.append(
            {
                "name": name,
                "version": "1.0",
                "scope": scope,
                "licenses": [{"expression": "MIT OR Apache-2.0"}],
                "purl": f"pkg:cargo/{name}@1.0",
                "bom-ref": f"registry+https://github.com/rust-lang/crates.io-index#{name}@1.0",
                "hashes": [{"alg": "SHA-256", "content": sha}],
            }
        )
        crates.append(
            {
                "name": name,
                "version": "1.0",
                "scope": scope,
                "licenses": [{"expression": "MIT OR Apache-2.0"}],
                "source_manifest_license": "MIT/Apache-2.0",
                "source": {
                    "file": path.name,
                    "sha256": sha,
                    "url": f"https://static.crates.io/crates/{name}/{path.name}",
                },
                "source_notices": {
                    name + "-1.0/LICENSE": digest(b"Original crate copyright\n")
                },
            }
        )
        lock += f'[[package]]\nname = "{name}"\nversion = "1.0"\nsource = "registry+https://github.com/rust-lang/crates.io-index"\nchecksum = "{sha}"\n'
    workspace = {
        "name": "local",
        "version": "0.1.0",
        "scope": "required",
        "licenses": [{"expression": "Apache-2.0"}],
    }
    components.append(dict(workspace, **{"bom-ref": "path+file:///local"}))
    record = json.dumps(
        {
            "components": components,
            "metadata": {"component": {"name": "wrapper", "version": "0.1.0"}},
        }
    ).encode()
    package = pins["packages"][0]
    source = cache / package["source"]["file"]
    with tarfile.open(source, "w:gz") as archive:
        member = tarfile.TarInfo("example-1.0/Cargo.lock")
        member.size = len(lock.encode())
        archive.addfile(member, io.BytesIO(lock.encode()))
    package["source"]["sha256"] = digest(source.read_bytes())
    wheel = cache / package["wheel"]["file"]
    filename = "example.dist-info/sboms/rust.json"
    with ZipFile(wheel, "a") as archive:
        archive.writestr(filename, record)
    package["wheel"]["sha256"] = digest(wheel.read_bytes())
    package["build_records"] = {filename: digest(record)}
    pins["rust_inventory"] = {
        "declared_by": {"package": "example", "member": filename},
        "cargo_lock": {
            "package": "example",
            "member": "example-1.0/Cargo.lock",
            "sha256": digest(lock.encode()),
        },
        "registry_components": crates,
        "workspace_components": [workspace],
    }
    return cache, pins, output


def test_rust_original_notices_cargo_binding_and_excluded_scope(rust_artifacts):
    cache, pins, output = rust_artifacts
    result = inventory.collect(pins, cache, output, source_cache=cache)
    assert result["artifacts_verified"] and result["rust_cargo_lock_verified"]
    assert (
        result["rust_source_notice_files"] == 2
        and not result["complete_native_inventory"]
    )
    assert result["rust_inventory"]["registry_components"][1]["scope"] == "excluded"
    assert (
        result["rust_inventory"]["registry_components"][0]["source_manifest_license"]
        == "MIT/Apache-2.0"
    )
    assert (
        output / "notices/rust-two/two-1.0/LICENSE"
    ).read_bytes() == b"Original crate copyright\n"
    assert (output / "build-records/example/example-1.0/Cargo.lock").is_file()


@pytest.mark.parametrize(
    "change", ["omit", "duplicate", "scope", "checksum", "url", "workspace"]
)
def test_rust_sbom_drift_stops_before_downloads(rust_artifacts, change):
    cache, pins, output = rust_artifacts
    rust = pins["rust_inventory"]
    if change == "omit":
        rust["registry_components"].pop()
    elif change == "duplicate":
        rust["registry_components"].append(
            copy.deepcopy(rust["registry_components"][0])
        )
    elif change == "workspace":
        rust["workspace_components"] = []
    elif change == "scope":
        rust["registry_components"][1]["scope"] = "required"
    else:
        rust["registry_components"][0]["source"][
            "sha256" if change == "checksum" else "url"
        ] = "a" * 64 if change == "checksum" else "https://example.test/crate"
    with pytest.raises(ValueError, match="Rust"):
        inventory.collect(pins, cache, output, source_cache=cache)
    assert not output.exists()


@pytest.mark.parametrize("update_pin", [False, True])
def test_cargo_lock_checksum_change_keeps_failed_inventory(rust_artifacts, update_pin):
    cache, pins, output = rust_artifacts
    package = pins["packages"][0]
    source = cache / package["source"]["file"]
    with tarfile.open(source) as archive:
        original = archive.extractfile("example-1.0/Cargo.lock").read()
    altered = original.replace(
        pins["rust_inventory"]["registry_components"][0]["source"]["sha256"].encode(),
        b"a" * 64,
    )
    with tarfile.open(source, "w:gz") as archive:
        member = tarfile.TarInfo("example-1.0/Cargo.lock")
        member.size = len(altered)
        archive.addfile(member, io.BytesIO(altered))
    package["source"]["sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
    if update_pin:
        pins["rust_inventory"]["cargo_lock"]["sha256"] = hashlib.sha256(
            altered
        ).hexdigest()
    result = inventory.collect(pins, cache, output, source_cache=cache)
    assert not result["artifacts_verified"] and not result["rust_cargo_lock_verified"]
    assert result["rust_source_notice_files"] == 0
    assert result["native_notice_failures"] == [
        {"component": "rust-cargo-lock", "error_class": "ValueError"}
    ]
    assert not (output / "notices/rust-one").exists()


def test_rust_wrong_source_manifest_license_fails_without_copying_notice(
    rust_artifacts,
):
    cache, pins, output = rust_artifacts
    pins["rust_inventory"]["registry_components"][0]["source_manifest_license"] = (
        "BSD-3-Clause"
    )
    result = inventory.collect(pins, cache, output, source_cache=cache)
    assert not result["artifacts_verified"] and result["rust_cargo_lock_verified"]
    assert result["rust_source_notice_files"] == 1
    assert result["native_notice_failures"] == [
        {"component": "rust-one", "error_class": "ValueError"}
    ]
    assert not (output / "notices/rust-one").exists()
