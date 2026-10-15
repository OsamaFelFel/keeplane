"""Use an already loaded kind image by its actual containerd manifest digest."""

import re


def pin_loaded_image(run, source, cluster):
    nodes = run("kind", "get", "nodes", "--name", cluster).stdout.decode().split()
    if not nodes:
        raise RuntimeError("No kind nodes found for the image fixture")
    digest = None
    for node in nodes:
        output = run("docker", "exec", node, "ctr", "-n", "k8s.io", "images",
                     "list", "name==" + source).stdout.decode().splitlines()
        if len(output) != 2:
            raise RuntimeError("Loaded kind image is missing or ambiguous")
        fields = output[1].split()
        if len(fields) < 3 or fields[0] != source:
            raise RuntimeError("Loaded kind image metadata is incomplete")
        current = fields[2]
        if not re.fullmatch(r"sha256:[a-f0-9]{64}", current):
            raise RuntimeError("Loaded kind image has no valid manifest digest")
        if digest is not None and current != digest:
            raise RuntimeError("Kind nodes contain different app image manifests")
        digest = current
    pinned = source.rsplit(":", 1)[0] + "@" + digest
    for node in nodes:
        output = run("docker", "exec", node, "ctr", "-n", "k8s.io", "images",
                     "list", "name==" + pinned).stdout.decode().splitlines()
        if len(output) > 1:
            if len(output) != 2 or output[1].split()[2] != digest:
                raise RuntimeError("Kind digest alias points at a different image")
            continue
        run("docker", "exec", node, "ctr", "-n", "k8s.io", "images",
            "tag", source, pinned)
    return pinned
