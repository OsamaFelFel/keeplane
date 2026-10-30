"""Chart checks find Helm from KEEPLANE_HELM_BIN or PATH, never a fixed path."""

import pytest

from tests.support.helm import HelmNotFound, require_helm, resolve_helm


def fake_which(executables):
    def which(name):
        return executables.get(name)

    return which


def test_configured_binary_wins_over_path():
    which = fake_which({"/opt/helm/helm": "/opt/helm/helm", "helm": "/usr/bin/helm"})
    environ = {"KEEPLANE_HELM_BIN": "/opt/helm/helm"}
    assert resolve_helm(environ, which) == "/opt/helm/helm"
    assert require_helm(environ, which) == "/opt/helm/helm"


def test_configured_name_is_looked_up_on_path():
    which = fake_which({"helm3": "/usr/local/bin/helm3"})
    assert resolve_helm({"KEEPLANE_HELM_BIN": "helm3"}, which) == "/usr/local/bin/helm3"


def test_path_is_used_when_nothing_is_configured():
    which = fake_which({"helm": "/usr/bin/helm"})
    assert resolve_helm({}, which) == "/usr/bin/helm"
    assert resolve_helm({"KEEPLANE_HELM_BIN": ""}, which) == "/usr/bin/helm"


def test_missing_helm_skips_with_setup_instructions():
    with pytest.raises(HelmNotFound, match="KEEPLANE_HELM_BIN"):
        resolve_helm({}, fake_which({}))
    with pytest.raises(pytest.skip.Exception) as skipped:
        require_helm({}, fake_which({}))
    assert "Helm 3" in str(skipped.value)
    assert "KEEPLANE_HELM_BIN" in str(skipped.value)
    assert "darwin" not in str(skipped.value)


def test_wrong_configured_binary_fails_instead_of_skipping():
    which = fake_which({"helm": "/usr/bin/helm"})
    environ = {"KEEPLANE_HELM_BIN": "/missing/helm"}
    with pytest.raises(HelmNotFound, match="KEEPLANE_HELM_BIN is set to '/missing/helm'"):
        require_helm(environ, which)


def test_real_lookup_uses_executable_from_environment(tmp_path, monkeypatch):
    helm = tmp_path / "helm"
    helm.write_text("#!/bin/sh\n")
    helm.chmod(0o755)
    monkeypatch.setenv("KEEPLANE_HELM_BIN", str(helm))
    assert require_helm() == str(helm)
    monkeypatch.delenv("KEEPLANE_HELM_BIN")
    monkeypatch.setenv("PATH", str(tmp_path))
    assert require_helm() == str(helm)
    helm.chmod(0o644)
    with pytest.raises(pytest.skip.Exception):
        require_helm()
