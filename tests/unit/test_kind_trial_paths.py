"""The kind trial's kubeconfig default works on macOS and Linux."""

from tests.support.kind_trial import default_kubeconfig, kind_kubeconfig


def test_kind_trial_kubeconfig_comes_from_the_environment(tmp_path):
    chosen = str(tmp_path / "config")
    assert kind_kubeconfig({"KEEPLANE_KUBECONFIG": chosen}, tmp_path) == chosen


def test_kind_trial_kubeconfig_keeps_the_macos_folder_when_it_exists(tmp_path):
    assert kind_kubeconfig({}, tmp_path) == str(tmp_path / "keeplane-kind-kubeconfig")


def test_kind_trial_kubeconfig_uses_tmp_where_private_tmp_is_missing(tmp_path):
    missing = tmp_path / "absent"
    assert default_kubeconfig(missing) == "/tmp/keeplane-kind-kubeconfig"
    assert kind_kubeconfig({"KEEPLANE_KUBECONFIG": ""}, missing) == (
        "/tmp/keeplane-kind-kubeconfig"
    )
