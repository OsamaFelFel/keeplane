"""Remove build-only Python installers and retain their distribution notices."""

import shutil
import subprocess
import sys
import sysconfig
from importlib.metadata import distribution
from pathlib import Path

package = distribution("pip")
notices = Path("/usr/share/keeplane/licenses") / f"pip-{package.version}"
notices.mkdir(parents=True, exist_ok=True)
for item in package.files:
    if item.parts[0].endswith(".dist-info") and item.parts[1] in (
        "licenses",
        "METADATA",
    ):
        target = notices.joinpath(*item.parts[1:])
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(package.locate_file(item), target)
shutil.copyfile(package.locate_file("pip/_vendor/vendor.txt"), notices / "vendor.txt")
subprocess.run([sys.executable, "-m", "pip", "uninstall", "--yes", "pip"], check=True)
shutil.rmtree(Path(sysconfig.get_path("stdlib")) / "ensurepip")
