"""Digest aliases use the containerd manifest, never a Docker configuration ID."""

from types import SimpleNamespace

import pytest

from tests.support.kind_images import pin_loaded_image


SOURCE = "docker.io/library/keeplane-preview:postgres-local"
DIGEST = "sha256:" + "a" * 64
PINNED = SOURCE.rsplit(":", 1)[0] + "@" + DIGEST


def fixture_runner(digests, existing=False):
    calls = []

    def run(*command):
        calls.append(command)
        if command[0] == "kind":
            output = "\n".join(digests)
        elif "list" in command:
            name = command[-1].removeprefix("name==")
            output = "REF TYPE DIGEST SIZE PLATFORMS LABELS\n"
            if name == SOURCE or existing:
                output += name + " manifest " + digests[command[2]] + " 1KiB linux/amd64 -\n"
        else:
            output = ""
        return SimpleNamespace(stdout=output.encode())

    return run, calls


def test_each_node_uses_the_same_loaded_manifest_without_registry_access():
    run, calls = fixture_runner({"node-a": DIGEST, "node-b": DIGEST})
    assert pin_loaded_image(run, SOURCE, "fixture") == PINNED
    assert [command[-2:] for command in calls if "tag" in command] == [
        (SOURCE, PINNED), (SOURCE, PINNED)]
    assert all("pull" not in command for command in calls)


def test_existing_digest_alias_is_reused():
    run, calls = fixture_runner({"node-a": DIGEST}, existing=True)
    assert pin_loaded_image(run, SOURCE, "fixture") == PINNED
    assert all("tag" not in command for command in calls)


@pytest.mark.parametrize("other", ["sha256:short", "sha256:" + "b" * 64])
def test_missing_or_different_manifests_refuse_before_aliasing(other):
    run, calls = fixture_runner({"node-a": DIGEST, "node-b": other})
    with pytest.raises(RuntimeError):
        pin_loaded_image(run, SOURCE, "fixture")
    assert all("tag" not in command for command in calls)
