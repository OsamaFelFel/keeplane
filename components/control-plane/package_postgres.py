"""Build-time installation of the verified, replaceable PostgreSQL driver."""

import hashlib
import json
from pathlib import Path
import subprocess
import sys
from urllib.request import urlopen


root = Path("/usr/share/keeplane")
metadata = json.loads((root / "licenses/psycopg-3.3.6.json").read_text())
sources = root / "sources"
sources.mkdir(parents=True, exist_ok=True)
if sys.argv[1] == "build":
    wheels = Path("/wheels")
    wheels.mkdir()
    native = json.loads((root / "licenses/psycopg-c-3.3.6.json").read_text())
    for artifact, destination in (
        (metadata["distribution"], wheels),
        (metadata["corresponding_source"], sources),
        (native["corresponding_source"], sources),
    ):
        with urlopen(artifact["url"], timeout=60) as response:
            data = response.read()
        if hashlib.sha256(data).hexdigest() != artifact["sha256"]:
            raise RuntimeError("PostgreSQL driver artifact checksum mismatch")
        name = artifact["url"].rsplit("/", 1)[1]
        (destination / name).write_bytes(data)
    subprocess.run(
        [
            "pip",
            "wheel",
            "--no-index",
            "--no-deps",
            "--no-build-isolation",
            "--wheel-dir",
            str(wheels),
            str(sources / "psycopg_c-3.3.6.tar.gz"),
        ],
        check=True,
    )
    (root / "postgres-build-packages.txt").write_text(
        subprocess.check_output(["apk", "info", "-v"], text=True)
    )
    sys.exit(0)

import psycopg

inventory = {
    "driver_version": psycopg.__version__,
    "driver_implementation": psycopg.pq.__impl__,
    "libpq_version": psycopg.pq.version(),
    "alpine_packages": subprocess.check_output(
        ["apk", "info", "-v"], text=True
    ).splitlines(),
    "libpq_package": subprocess.check_output(["apk", "info", "-a", "libpq"], text=True),
    "libpq_shared_libraries": subprocess.check_output(
        ["ldd", "/usr/lib/libpq.so.5"], text=True
    ),
    "limits": [
        "This records the installed runtime, not release approval of the complete base image.",
        "Preserve native package sources, patches and notices with the final distribution.",
    ],
}
(root / "postgres-package.json").write_text(json.dumps(inventory, indent=2) + "\n")
