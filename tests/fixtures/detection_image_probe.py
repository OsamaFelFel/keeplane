"""Load the bundled detector inside a packaged detection image.

Runs as the image's own user, with no network and a read-only root
filesystem, as the Kubernetes chart runs the app. Prints only timings and
memory, never request text. Case DI-01 in
tests/integration/detection-image-cases.md.
"""

import importlib.util
import json
import os
import resource
import sys
import time
from pathlib import Path

sys.path.insert(0, "/app")

LOAD_LIMIT_SECONDS = 300
MEMORY_LIMIT_MIB = 1024

assert os.getuid() == 65532, os.getuid()
assert importlib.util.find_spec("pip") is None
model = os.environ.get("KEEPLANE_PERSONAL_DATA_MODEL")
assert model == "en_core_web_lg", model
assert "KEEPLANE_PERSONAL_DATA_DETECTION" not in os.environ
notices = Path("/usr/share/keeplane/licenses")
for name in ("personal-data-detection.md", "personal-data-detection.json",
             "presidio-analyzer-2.2.364-LICENSE.txt"):
    assert (notices / name).is_file(), name
for place in ("/app", "/usr/local/lib", "/tmp", os.path.expanduser("~")):
    try:
        Path(place, "keeplane-write-probe").write_text("x")
    except OSError:
        continue
    raise AssertionError(f"{place} is writable; run the probe with --read-only")

from personal_data.engine import PresidioDetector, installed  # noqa: E402
from personal_data.inspection import FOUND, CLEAN, Inspector  # noqa: E402

assert installed(model)
start = time.monotonic()
detector = PresidioDetector(model)
load_seconds = time.monotonic() - start

# Every value is invented: an example.com address and a fiction-range phone.
inspector = Inspector(lambda: detector)
for _ in range(100):
    if inspector.detector() is not None:
        break
    time.sleep(0.05)
held = inspector.check("Email amara.okonkwo@example.com the summary, or call 020 7946 0958.")
assert held.held and held.reason == FOUND, held
timings = []
for _ in range(20):
    began = time.monotonic()
    clean = inspector.check("Refactor the parser so that it yields tokens lazily.")
    timings.append(time.monotonic() - began)
    assert not clean.held and clean.reason == CLEAN, clean
timings.sort()
max_rss_mib = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
print(json.dumps({
    "load_seconds": round(load_seconds, 2),
    "short_check_ms_median": round(timings[len(timings) // 2] * 1000, 1),
    "max_rss_mib": round(max_rss_mib),
}))
assert load_seconds < LOAD_LIMIT_SECONDS, load_seconds
assert max_rss_mib < MEMORY_LIMIT_MIB, max_rss_mib
