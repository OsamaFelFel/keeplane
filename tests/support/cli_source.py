"""Load the developer CLI from a source checkout as its own package.

The CLI also runs as a script, importing its modules by bare name (``import
usage``). In a test process those names can already belong to the control
plane, which is on the path for Django: its ``usage`` app would shadow the
CLI's ``usage.py``. Loading the CLI as a package under a name of its own keeps
every CLI module separate from the control plane's.
"""

import importlib.util
import os
import sys
from pathlib import Path

import pytest

PACKAGE = "keeplane_cli_under_test"


def load_cli(monkeypatch, default):
    """The CLI's ``keeplane`` module, from ``KEEPLANE_CLI_SOURCE`` or ``default``."""
    source = Path(os.environ.get("KEEPLANE_CLI_SOURCE", default))
    folder = source / "components/cli"
    if not (folder / "keeplane.py").is_file() or not (folder / "__init__.py").is_file():
        if "KEEPLANE_CLI_SOURCE" in os.environ:
            pytest.fail("The explicitly configured CLI source is unavailable")
        pytest.skip(
            "Compose the reviewed browser/profile CLI before this optional journey"
        )
    # A fresh copy for each test: earlier tests' patches never carry over.
    for name in [key for key in sys.modules if key.split(".")[0] == PACKAGE]:
        monkeypatch.delitem(sys.modules, name)
    spec = importlib.util.spec_from_file_location(
        PACKAGE, folder / "__init__.py", submodule_search_locations=[str(folder)]
    )
    package = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, PACKAGE, package)
    spec.loader.exec_module(package)
    return importlib.import_module(PACKAGE + ".keeplane")
