#!/usr/bin/env python3
"""Install the protected developer release on the isolated kind network.

Used by the isolated-network job (tests/e2e/kubernetes-isolated-cases.md,
ISO-13 to ISO-19) while the outside registries are still reachable:

  protected.py certificates
      With the run's CA (<runtime>/ca.crt and ca.key), sign the account
      database's certificate (name "db"), the public address's
      (keeplane-protected.isolated.test) and the model provider's
      (api.openai.com and 172.30.0.1, the runner on the isolated network),
      into <runtime>/protected/. The workflow starts the HTTPS provider
      fixture on the runner with the last one.

  protected.py install
      Install the release with deploy/local/kind_protected.py's steps, in
      namespace keeplane-protected beside the local-trial release: the same
      Secrets, account and gateway databases, database roles and chart
      values (deploy/local/protected-values.yaml), plus protected-values.yaml
      next to this script. What differs: it refuses any Kubernetes context
      but kind-keeplane-isolated; the app image is the one in the internal
      registry, by digest (KEEPLANE_ISOLATED_PROTECTED_IMAGE); the model
      provider runs outside the cluster on the runner, so the cluster DNS
      points api.openai.com to 172.30.0.1 and no provider runs in the
      namespace; and the ingress controller is the one the job installed.

The kubeconfig and the run's folder come from KEEPLANE_ISOLATED_KUBECONFIG and
KEEPLANE_ISOLATED_RUNTIME. No key or password is printed.
"""

import importlib.util
import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
_spec = importlib.util.spec_from_file_location(
    "kind_protected", ROOT / "deploy/local/kind_protected.py"
)
kind_protected = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(kind_protected)

CONTEXT = "kind-keeplane-isolated"
HOST = "keeplane-protected.isolated.test"
# The runner on the isolated network: where the provider fixture listens.
PROVIDER_ADDRESS = "172.30.0.1"
MIRROR = "172.30.0.200:5000"
VALUES = "tests/fixtures/isolated-network/protected-values.yaml"
# Each certificate the run's CA signs here: its file stem and its names.
CERTIFICATES = {
    "db": ("DNS:db",),
    "public": ("DNS:" + HOST,),
    "provider": ("DNS:" + kind_protected.PROVIDER_HOST, "IP:" + PROVIDER_ADDRESS),
}
PINNED = re.compile(re.escape(MIRROR) + r"/[a-z0-9/._-]+@sha256:[0-9a-f]{64}")


def image_refusal(image):
    """Why the app image can't be used, or None for one pinned in the mirror."""
    if PINNED.fullmatch(image or ""):
        return None
    return (
        "KEEPLANE_ISOLATED_PROTECTED_IMAGE must name the app image in the "
        f"internal registry by digest ({MIRROR}/...@sha256:...)"
    )


class IsolatedInstaller(kind_protected.Installer):
    context = CONTEXT
    public_url = "https://" + HOST
    values = (*kind_protected.Installer.values, VALUES)

    def __init__(self, kubeconfig, runtime, helm, image=""):
        super().__init__(kubeconfig, runtime, helm)
        self.state = self.runtime / "protected"
        self.image_ref = image

    def sign(self):
        """The three certificates, signed with the run's CA; its key stays put."""
        self.state.mkdir(mode=0o700, exist_ok=True)
        ca, ca_key = self.runtime / "ca.crt", self.runtime / "ca.key"
        with tempfile.TemporaryDirectory(prefix="keeplane-isolated-protected-") as work:
            work = Path(work)
            for stem, names in CERTIFICATES.items():
                config = work / f"{stem}.cnf"
                config.write_text(
                    kind_protected.TLS_CONFIG.format(
                        name=names[0][4:], names=",".join(names)
                    )
                )
                key = self.state / f"{stem}.key"
                self.run(
                    "openssl", "req", "-new", "-newkey", "rsa:2048", "-nodes", "-sha256",
                    "-keyout", str(key), "-out", str(work / f"{stem}.csr"),
                    "-config", str(config), timeout=60,
                )  # fmt: skip
                key.chmod(0o600)
                self.run(
                    "openssl", "x509", "-req", "-in", str(work / f"{stem}.csr"),
                    "-CA", str(ca), "-CAkey", str(ca_key), "-CAcreateserial",
                    "-out", str(self.state / f"{stem}.pem"), "-days", "1", "-sha256",
                    "-extfile", str(config), "-extensions", "leaf", timeout=60,
                )  # fmt: skip
        (self.state / "ca.pem").write_bytes(ca.read_bytes())

    def certificates(self):
        self.tls = {"ca.pem": (self.state / "ca.pem").read_bytes()}
        for stem in CERTIFICATES:
            for kind in ("pem", "key"):
                self.tls[f"{stem}.{kind}"] = (
                    self.state / f"{stem}.{kind}"
                ).read_bytes()

    def image(self):
        refusal = image_refusal(self.image_ref)
        if refusal:
            raise SystemExit(refusal)
        self.pinned = self.image_ref

    def provider_fixture(self):
        # The provider runs on the runner; the release trusts the run's CA.
        self.configmap("cloud-provider-ca", {"ca.crt": self.tls["ca.pem"].decode()})

    def provider_address(self):
        return PROVIDER_ADDRESS

    def ingress_controller(self):
        pass  # The workflow installed ingress-nginx for both releases.


def main(argv):
    if argv not in (["certificates"], ["install"]):
        raise SystemExit(__doc__)
    installer = IsolatedInstaller(
        os.environ["KEEPLANE_ISOLATED_KUBECONFIG"],
        os.environ["KEEPLANE_ISOLATED_RUNTIME"],
        os.environ.get("KEEPLANE_HELM_BIN", "helm"),
        os.environ.get("KEEPLANE_ISOLATED_PROTECTED_IMAGE", ""),
    )
    if argv == ["certificates"]:
        installer.sign()
    else:
        installer.install()
        print(f"Keeplane protected developer release: {installer.public_url}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
