#!/usr/bin/env python3
"""Fill the isolated network's internal registry and point the node at it.

Used by the isolated-network job (tests/e2e/kubernetes-isolated-cases.md)
while the outside registries are still reachable:

  mirror.py fill LIST MANIFEST... [--image REF]...
      Copy every image the manifests name (each `image:` line), and any
      --image, from its registry into the internal registry, keeping its
      digest, and write what was copied to LIST (JSON). Every image must be
      pinned by digest. An image that is already in the internal registry
      (the app image the job pushes there) is only checked.

  mirror.py point-node LIST
      Configure the node's containerd to pull every registry in LIST through
      the internal registry first, and the internal registry itself over
      plain HTTP inside the network.

An image from registry R with path P is kept in the internal registry at
R/P (for example quay.io/calico/node), so images from different registries
never collide; the node's containerd maps R to that prefix. For an image
index only the linux/amd64 image is copied, as registry.yml requires; the
index itself is copied byte for byte, so its digest is unchanged.
"""

import json
import re
import subprocess
import sys
from urllib.error import HTTPError
from urllib.request import Request, urlopen

# The internal registry: its address on the isolated network, which the node
# pulls from, and its port published on the runner's loopback, which this
# script pushes to.
MIRROR = "172.30.0.200:5000"
PUSH = "127.0.0.1:5001"
NODE = "keeplane-isolated-control-plane"
CERTS = "/etc/containerd/certs.d"
PLATFORM = {"os": "linux", "architecture": "amd64"}
INDEX = {
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
}
ACCEPT = ", ".join(
    sorted(INDEX)
    + [
        "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.docker.distribution.manifest.v2+json",
    ]
)
IMAGE_LINE = re.compile(r"""^\s*(?:-\s*)?image:\s*["']?([^"'\s#]+)""", re.MULTILINE)
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


def split(ref):
    """Split a pinned image reference into registry, path, tag and digest."""
    name, _, digest = ref.partition("@")
    if not DIGEST.match(digest):
        raise SystemExit(f"{ref} is not pinned by digest")
    first, _, rest = name.partition("/")
    if rest and ("." in first or ":" in first or first == "localhost"):
        registry, path = first, rest
    else:
        registry, path = "docker.io", name
    path, _, tag = path.partition(":")
    if registry == "docker.io" and "/" not in path:
        path = "library/" + path
    return registry, path, tag, digest


def mirror_path(registry, path):
    return path if registry == MIRROR else f"{registry}/{path}"


def run(*command, binary=False):
    result = subprocess.run(command, check=False, capture_output=True, text=not binary)
    if result.returncode:
        err = result.stderr if not binary else result.stderr.decode(errors="replace")
        raise SystemExit(f"{' '.join(command[:3])} failed: {err[-600:]}")
    return result.stdout


def head(path, reference):
    """The internal registry's digest for path:reference, or None."""
    request = Request(
        f"http://{PUSH}/v2/{path}/manifests/{reference}",
        method="HEAD",
        headers={"Accept": ACCEPT},
    )
    try:
        with urlopen(request, timeout=30) as response:
            return response.headers.get("Docker-Content-Digest")
    except HTTPError:
        return None


def put_manifest(path, reference, raw, media_type):
    request = Request(
        f"http://{PUSH}/v2/{path}/manifests/{reference}",
        data=raw,
        method="PUT",
        headers={"Content-Type": media_type},
    )
    with urlopen(request, timeout=60) as response:
        return response.headers.get("Docker-Content-Digest")


def copy(ref):
    registry, path, tag, digest = split(ref)
    target = mirror_path(registry, path)
    entry = {"image": ref, "registry": registry, "path": target, "digest": digest}
    if registry == MIRROR:
        if head(target, digest) != digest:
            raise SystemExit(f"{ref} is not in the internal registry")
        return entry
    source = f"{registry}/{path}@{digest}"
    tag = tag or "pinned-" + digest[7:19]
    raw = run("crane", "manifest", source, binary=True)
    manifest = json.loads(raw)
    media_type = manifest.get("mediaType") or (
        "application/vnd.oci.image.index.v1+json"
        if "manifests" in manifest
        else "application/vnd.oci.image.manifest.v1+json"
    )
    if media_type in INDEX:
        children = [
            m["digest"]
            for m in manifest["manifests"]
            if all(m.get("platform", {}).get(k) == v for k, v in PLATFORM.items())
            and not m.get("platform", {}).get("variant")
        ]
        if len(children) != 1:
            raise SystemExit(f"{ref} has {len(children)} linux/amd64 images")
        child = children[0]
        run(
            "crane",
            "copy",
            "--insecure",
            f"{registry}/{path}@{child}",
            f"{PUSH}/{target}:{tag}",
        )
        if head(target, child) != child:
            raise SystemExit(f"{ref}: its linux/amd64 image did not arrive")
        entry["platform_digest"] = child
        stored = put_manifest(target, digest, raw, media_type)
        put_manifest(target, tag, raw, media_type)
    else:
        run("crane", "copy", "--insecure", source, f"{PUSH}/{target}:{tag}")
        stored = head(target, digest)
    if stored != digest or head(target, digest) != digest:
        raise SystemExit(f"{ref} arrived as {stored}, not {digest}")
    return entry


def fill(out, sources, extra):
    refs = set(extra)
    for source in sources:
        with open(source) as handle:
            refs |= set(IMAGE_LINE.findall(handle.read()))
    if not refs:
        raise SystemExit("No images found")
    copied = []
    for ref in sorted(refs):
        entry = copy(ref)
        copied.append(entry)
        print(f"{ref} -> {MIRROR}/{entry['path']}@{entry['digest']}", flush=True)
    with open(out, "w") as handle:
        json.dump(copied, handle, indent=2)
        handle.write("\n")


def write_in_node(path, text):
    folder = path.rsplit("/", 1)[0]
    subprocess.run(
        [
            "docker",
            "exec",
            "-i",
            NODE,
            "sh",
            "-c",
            f"mkdir -p '{folder}' && cat > '{path}'",
        ],
        input=text,
        text=True,
        check=True,
    )


def point_node(listing):
    with open(listing) as handle:
        registries = sorted({entry["registry"] for entry in json.load(handle)})
    dump = run("docker", "exec", NODE, "containerd", "config", "dump")
    if not re.search(r"config_path\s*=\s*[\"']" + re.escape(CERTS) + "[\"']", dump):
        found = [line.strip() for line in dump.splitlines() if "config_path" in line]
        raise SystemExit(f"containerd does not read {CERTS}: {found}")
    write_in_node(f"{CERTS}/{MIRROR}/hosts.toml", f'server = "http://{MIRROR}"\n')
    for registry in registries:
        if registry == MIRROR:
            continue
        upstream = "registry-1.docker.io" if registry == "docker.io" else registry
        write_in_node(
            f"{CERTS}/{registry}/hosts.toml",
            f'server = "https://{upstream}"\n\n'
            f'[host."http://{MIRROR}/v2/{registry}"]\n'
            '  capabilities = ["pull", "resolve"]\n'
            "  override_path = true\n",
        )
        print(f"{registry} -> http://{MIRROR}/v2/{registry}")


def main(argv):
    if len(argv) >= 3 and argv[0] == "fill":
        sources, extra, args = [], [], iter(argv[2:])
        for arg in args:
            if arg == "--image":
                extra.append(next(args))
            else:
                sources.append(arg)
        fill(argv[1], sources, extra)
    elif len(argv) == 2 and argv[0] == "point-node":
        point_node(argv[1])
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
