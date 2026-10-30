"""Find the Helm 3 binary used by chart and Kubernetes checks."""

import os
import shutil

import pytest


ENV_VAR = "KEEPLANE_HELM_BIN"
MISSING = (
    f"Helm 3 was not found. Install Helm 3.19 or newer on PATH, or set {ENV_VAR} "
    "to the Helm binary."
)


class HelmNotFound(RuntimeError):
    """Raised when no usable Helm binary is configured or on PATH."""


def resolve_helm(environ=None, which=shutil.which):
    """Return KEEPLANE_HELM_BIN, else helm on PATH, else raise HelmNotFound."""
    environ = os.environ if environ is None else environ
    configured = environ.get(ENV_VAR)
    if configured:
        found = which(configured)
        if not found:
            raise HelmNotFound(
                f"{ENV_VAR} is set to {configured!r}, which is not an executable "
                "Helm binary."
            )
        return found
    found = which("helm")
    if not found:
        raise HelmNotFound(MISSING)
    return found


def require_helm(environ=None, which=shutil.which):
    """Return Helm, skipping when absent; a wrong KEEPLANE_HELM_BIN fails."""
    environ = os.environ if environ is None else environ
    try:
        return resolve_helm(environ, which)
    except HelmNotFound as error:
        if environ.get(ENV_VAR):
            raise
        pytest.skip(str(error), allow_module_level=True)
