"""The protected kind release's setup: cases KPS-01 to KPS-06 and KPS-08.

See kind-protected-setup-cases.md. KPS-01 to KPS-05 check
deploy/local/kind_protected.py's own steps and KPS-06 the launcher's settings
check. KPS-07, the rendered release, is in
tests/integration/test_kind_protected_values.py.
"""

import importlib.util
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "kind_protected", ROOT / "deploy/local/kind_protected.py"
)
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)

# kind's default cluster DNS settings (kindest/node v1.37.0).
KIND_COREFILE = """.:53 {
    errors
    health {
       lameduck 5s
    }
    ready
    kubernetes cluster.local in-addr.arpa ip6.arpa {
       pods insecure
       fallthrough in-addr.arpa ip6.arpa
       ttl 30
    }
    prometheus :9153
    forward . /etc/resolv.conf {
       max_concurrent 1000
    }
    cache 30
    loop
    reload
    loadbalance
}
"""
PASSWORDS = {
    "app": "a" * 43,
    "migration": "m" * 43,
    "enroller": "e" * 43,
    "status-0": "s" * 43,
    "status-1": "t" * 43,
}


def test_kps_01_the_provider_name_points_to_the_fixture_once():
    changed = setup.with_provider_host(KIND_COREFILE, "10.96.0.50")
    assert "        10.96.0.50 api.openai.com\n        fallthrough\n    }" in changed
    # Right after `ready`, and everything else is kept as it was.
    assert (
        changed.index("ready") < changed.index("hosts {") < changed.index("kubernetes")
    )
    assert (
        changed.replace(
            changed[
                changed.index("    " + setup.MARK) : changed.index(
                    "    }\n    kubernetes"
                )
                + 6
            ],
            "",
        )
        == KIND_COREFILE
    )
    # A later start replaces the entry instead of adding a second one.
    again = setup.with_provider_host(changed, "10.96.0.51")
    assert again.count("hosts {") == 1
    assert "10.96.0.51 api.openai.com" in again and "10.96.0.50" not in again


@pytest.mark.parametrize(
    ("corefile", "address", "problem"),
    [
        (KIND_COREFILE.replace("    ready\n", "    ready\n    hosts {\n    }\n"),
         "10.96.0.50", "already has a hosts block"),
        (KIND_COREFILE.replace("    ready\n", ""), "10.96.0.50", "not kind's defaults"),
        (KIND_COREFILE, "", "no cluster address"),
        (KIND_COREFILE, "cloud-provider", "no cluster address"),
    ],
    ids=["installer-hosts", "not-kind", "no-address", "a-name"],
)  # fmt: skip
def test_kps_02_other_dns_settings_are_left_alone(corefile, address, problem):
    with pytest.raises(ValueError, match=problem):
        setup.with_provider_host(corefile, address)


def test_kps_03_the_roles_follow_the_roles_guide():
    sql = setup.roles_sql(PASSWORDS)
    created = re.findall(
        r"CREATE ROLE (\w+) LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT", sql
    )
    assert created == [
        "keeplane_migrate", "keeplane_app", "keeplane_enroller",
        "keeplane_status_0", "keeplane_status_1",
    ]  # fmt: skip
    # The enroller and each status role are read-only by default.
    assert re.findall(r"ALTER ROLE (\w+) SET default_transaction_read_only = on;", sql) == [
        "keeplane_enroller", "keeplane_status_0", "keeplane_status_1",
    ]  # fmt: skip
    assert "CREATE DATABASE keeplane OWNER keeplane_migrate;" in sql
    assert (
        "GRANT CONNECT ON DATABASE keeplane TO keeplane_app, keeplane_enroller, "
        "keeplane_status_0, keeplane_status_1;" in sql
    )
    for unsafe in ("SUPERUSER ", "BYPASSRLS", " CREATEROLE", "GRANT keeplane_"):
        assert unsafe not in sql.replace("NOSUPERUSER", "").replace("NOCREATEROLE", "")
    # Only the app role gets table access; the migration Job sets the rest.
    assert "TO keeplane_app;" in setup.SCHEMA_SQL
    assert "keeplane_enroller" not in setup.SCHEMA_SQL
    # The status roles match the chart values, one per gateway copy.
    assert setup.STATUS_ROLES == ("keeplane_status_0", "keeplane_status_1")


def test_kps_04_a_password_that_could_change_the_sql_is_refused():
    with pytest.raises(ValueError, match="URL-safe"):
        setup.roles_sql({**PASSWORDS, "app": "x' SUPERUSER; --" + "a" * 32})


def test_kps_05_the_public_name_must_point_to_this_computer():
    assert setup.resolves_here("localhost")
    assert not setup.resolves_here("keeplane-unknown.invalid")
    assert "127.0.0.1 keeplane.kind.test" in setup.HOSTS_MISSING


def launcher(tmp_path, protected):
    """Run kind-up.sh with stub tools, stopping before any build or cluster work."""
    root = tmp_path / "repo"
    (root / "deploy/local").mkdir(parents=True)
    for name in ("kind-up.sh", "kind_protected.py"):
        shutil.copy(ROOT / "deploy/local" / name, root / "deploy/local" / name)
    commands = tmp_path / "bin"
    commands.mkdir()
    for tool in ("dirname", "mkdir", "chmod"):
        (commands / tool).symlink_to(shutil.which(tool))
    (commands / "python3").symlink_to(sys.executable)
    for name in (
        "node",
        "npm",
        "docker",
        "kind",
        "kubectl",
        "helm",
        "shasum",
        "openssl",
    ):
        content = {"node": 'printf "v22.12.0\\n"\n', "docker": "exit 0\n"}.get(
            name, "exit 1\n"
        )
        (commands / name).write_text("#!/bin/sh\n" + content)
        (commands / name).chmod(0o755)
    runtime = tmp_path / "runtime"
    result = subprocess.run(
        ["/bin/sh", str(root / "deploy/local/kind-up.sh")],
        check=False, cwd=tmp_path, capture_output=True, text=True, timeout=30,
        env={**os.environ, "PATH": str(commands), "KEEPLANE_RUNTIME_DIR": str(runtime),
             "KEEPLANE_KIND_QWEN": "off", "KEEPLANE_KIND_PROTECTED": protected,
             "KEEPLANE_KUBECONFIG": str(tmp_path / "kubeconfig")},
    )  # fmt: skip
    return result, runtime


@pytest.mark.parametrize(
    ("protected", "message"),
    [
        ("maybe", "KEEPLANE_KIND_PROTECTED must be on or off."),
        # The sandbox has no /etc/hosts line for the public name.
        ("on", "127.0.0.1 keeplane.kind.test"),
    ],
)
def test_kps_06_the_launcher_checks_the_protected_setting_before_state_work(
    tmp_path, protected, message
):
    if protected == "on" and setup.resolves_here():
        pytest.skip("keeplane.kind.test points to this computer here")
    result, runtime = launcher(tmp_path, protected)
    assert result.returncode == 1
    assert message in result.stderr
    assert "Traceback" not in result.stderr
    assert not runtime.exists()


def test_kps_08_only_the_local_kind_cluster_is_changed(tmp_path, monkeypatch):
    assert setup.context_refusal("kind-keeplane") is None
    for other in ("prod-eu", "kind-keeplane-isolated", "kind-keeplane-netpol", ""):
        assert "Refusing Kubernetes context" in setup.context_refusal(other)
    # install() stops at the context check: no credential, build or kubectl change.
    calls = []

    def run(*command, **options):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, b"prod-eu\n", b"")

    installer = setup.Installer(
        str(tmp_path / "kubeconfig"), tmp_path / "runtime", "helm"
    )
    monkeypatch.setattr(installer, "run", run)
    with pytest.raises(SystemExit, match="Refusing Kubernetes context 'prod-eu'"):
        installer.install()
    assert calls == [
        (
            "kubectl",
            "--kubeconfig",
            str(tmp_path / "kubeconfig"),
            "config",
            "current-context",
        )
    ]
    assert not (tmp_path / "runtime").exists()
