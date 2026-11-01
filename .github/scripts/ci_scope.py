"""Skip application jobs only for an explicitly recognized documentation diff."""

import json
import os
import re
import subprocess
from pathlib import Path, PurePosixPath

# Guides whose commands a test checks against the code; editing one runs the
# application checks so the guide can't drift from what it describes. Every
# guide with kubectl commands is checked against the example Roles
# (tests/integration/test_chart_namespace_permissions.py).
CHECKED_GUIDES = {
    "docs/guide/backup-and-restore.md",
    "docs/guide/certificate-operations.md",
    "docs/guide/data-classes-local.md",
    "docs/guide/gateway-configuration.md",
    "docs/guide/gateway-database-secret.md",
    "docs/guide/kubernetes-installation-reference.md",
    "docs/guide/kubernetes-local.md",
    "docs/guide/kubernetes-namespace-permissions.md",
    "docs/guide/postgres-accounts.md",
}


def docs_only(event_name, event_path, *, directory=None):
    if event_name != "pull_request":
        return False
    try:
        with Path(event_path).open("rb") as stream:
            raw = stream.read(65537)
        if len(raw) > 65536:
            return False
        event = json.loads(raw)
        pull = event["pull_request"]
        base, head = pull["base"]["sha"], pull["head"]["sha"]
        if any(
            not isinstance(sha, str)
            or not re.fullmatch(r"[a-f0-9]{40}", sha)
            or sha == "0" * 40
            for sha in (base, head)
        ):
            return False
        result = subprocess.run(
            [
                "git",
                "diff",
                "--raw",
                "-z",
                "--no-renames",
                "--no-ext-diff",
                "--no-textconv",
                base,
                head,
            ],
            cwd=directory,
            capture_output=True,
            check=True,
            timeout=10,
        )
        fields = result.stdout.split(b"\0")
        if len(fields) < 3 or fields[-1] or len(fields) % 2 != 1:
            return False
        for metadata, name in zip(fields[::2], fields[1::2], strict=False):
            parts = metadata.split()
            if len(parts) != 5 or (parts[0], parts[1], parts[-1]) not in {
                (b":100644", b"100644", b"M"),
                (b":000000", b"100644", b"A"),
            }:
                return False
            path = name.decode("utf-8")
            allowed = path not in CHECKED_GUIDES and (
                path in {"README.md", "components/cli/README.md"}
                or (path.startswith("docs/") and PurePosixPath(path).suffix == ".md")
            )
            if not allowed:
                return False
        return True
    except (
        OSError,
        ValueError,
        TypeError,
        KeyError,
        RecursionError,
        subprocess.SubprocessError,
    ):
        return False


if __name__ == "__main__":
    selected = docs_only(
        os.environ.get("GITHUB_EVENT_NAME"), os.environ.get("GITHUB_EVENT_PATH")
    )
    with Path(os.environ["GITHUB_OUTPUT"]).open("a") as output:
        output.write("docs_only=" + str(selected).lower() + "\n")
    print(
        "Documentation-only pull request."
        if selected
        else "Run full application checks."
    )
