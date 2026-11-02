"""Where the local kind trial keeps its kubeconfig.

`KEEPLANE_KUBECONFIG` names the file. Without it, macOS keeps the earlier
`/private/tmp/keeplane-kind-kubeconfig` and Linux uses
`/tmp/keeplane-kind-kubeconfig`, the defaults `deploy/local/kind-up.sh` uses.
The trial's private files (first-admin password, gateway keys) follow
`tests/support/client.py`'s `RUNTIME`, set with `KEEPLANE_RUNTIME_DIR`.
"""

import os
from pathlib import Path


MAC_TEMPORARY = Path("/private/tmp")
CONTEXT = "kind-keeplane"


def default_kubeconfig(temporary=MAC_TEMPORARY):
    folder = temporary if temporary.is_dir() else Path("/tmp")
    return str(folder / "keeplane-kind-kubeconfig")


def kind_kubeconfig(environ=None, temporary=MAC_TEMPORARY):
    environ = os.environ if environ is None else environ
    return environ.get("KEEPLANE_KUBECONFIG") or default_kubeconfig(temporary)
