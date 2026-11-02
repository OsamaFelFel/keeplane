"""List the Python packages installed in a packaged image and check them.

Case DI-02 in tests/integration/detection-image-cases.md. Each distribution
is installed once, and every package in a licence inventory that this image
carries is installed at exactly the inventory's version. Arguments: the
inventory files under /app/licenses that this image target must carry.
"""

import json
import sys
from collections import defaultdict
from importlib.metadata import distributions
from pathlib import Path


def normal(name):
    return name.lower().replace("_", "-").replace(".", "-")


installed = defaultdict(list)
for dist in distributions():
    installed[normal(dist.metadata["Name"])].append(dist.version)
duplicates = {name: versions for name, versions in installed.items() if len(versions) > 1}
assert not duplicates, f"installed more than once: {duplicates}"

checked = 0
for inventory in sys.argv[1:]:
    rows = json.loads(Path("/app/licenses", inventory).read_text())["packages"]
    for row in rows:
        name = normal(row["name"])
        assert installed.get(name) == [row["version"]], (
            inventory, name, row["version"], installed.get(name))
        checked += 1
print(json.dumps({"distributions": len(installed), "inventory_packages_checked": checked}))
