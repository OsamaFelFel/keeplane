"""KPS-07 in tests/unit/kind-protected-setup-cases.md: render the protected kind release.

Renders deploy/local/protected-values.yaml with Helm, as
deploy/local/kind_protected.py installs it; skipped when Helm is missing, like
the other chart checks.
"""

import importlib.util
import re
from pathlib import Path

from tests.integration.test_chart_package import manifests, run

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "kind_protected", ROOT / "deploy/local/kind_protected.py"
)
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


def test_kps_07_the_values_render_the_protected_release():
    image = "docker.io/library/keeplane-protected@sha256:" + "a" * 64
    result = run(
        "template", setup.RELEASE, "deploy/helm/keeplane", "--namespace", setup.NAMESPACE,
        "-f", "deploy/local/protected-values.yaml", "--set", "app.image=" + image,
    )  # fmt: skip
    assert result.returncode == 0, result.stderr
    output = result.stdout
    kinds = sorted(re.findall(r"^kind: (\w+)$", output, re.MULTILINE))
    assert kinds.count("Ingress") == 2 and "StatefulSet" in kinds
    assert '"https://keeplane.kind.test/v1"' in output
    assert "name: KEEPLANE_CLI_OAUTH_ENABLED" in output
    assert "name: KEEPLANE_GUARD_STATUS_CHECK" in output
    assert "name: model-enroller" in output and "name: prepare-model-enroller" in output
    assert "register_cli_client --device" in output
    assert "--copy keeplane-gateway-1=keeplane_status_1" in output
    # Every image the release runs is pinned by digest.
    images = re.findall(r"^\s*(?:- )?image: \"?([^\"\s]+)\"?\s*$", output, re.MULTILINE)
    assert images and all(
        re.fullmatch(r"[^@\s]+@sha256:[0-9a-f]{64}", i) for i in images
    )
    assert image in images
    # Each Secret and ConfigMap the release reads is one kind_protected.py makes.
    script = (ROOT / "deploy/local/kind_protected.py").read_text()
    made = set(re.findall(r'self\.(?:secret|configmap)\(\s*"([\w-]+)"', script))
    read = set(re.findall(r"(?:secretName|claimName): \"?([\w-]+)\"?", output))
    read |= {
        name
        for document in manifests(output)
        for name in re.findall(r"secretKeyRef:\s*\n\s*name: \"?([\w-]+)\"?", document)
    }
    read |= set(re.findall(r"configMap:\s*\n\s*name: \"?([\w-]+)\"?", output))
    read -= {f"{setup.RELEASE}-config", "keeplane-provider-keys"}
    assert read and read <= made, sorted(read - made)
