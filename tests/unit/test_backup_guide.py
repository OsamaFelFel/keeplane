"""The backup guide's commands match the Docker preview, the chart and the app.

Cases BKG-01 to BKG-09 in backup-guide-cases.md. Nothing here starts Docker,
Kubernetes or Helm: the guide's shell blocks are read as text and checked
against compose.yaml, the app image, the chart templates and the app's own
management commands, so a rename in any of them fails here first.
"""

import json
import os
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest
from django.core.management import get_commands, load_command_class

from tests.integration.test_backup_restore import COPY_IN, SQLITE_COPY

ROOT = Path(__file__).resolve().parents[2]
GUIDE_PATH = ROOT / "docs/guide/backup-and-restore.md"
GUIDE = GUIDE_PATH.read_text()
COMPOSE = (ROOT / "compose.yaml").read_text()
DOCKERFILE = (ROOT / "components/control-plane/Dockerfile").read_text()
SETTINGS = (ROOT / "components/control-plane/config/settings.py").read_text()
TEMPLATES = ROOT / "deploy/helm/keeplane/templates"
APP_TEMPLATE = (TEMPLATES / "app.yaml").read_text()
GATEWAY_TEMPLATE = (TEMPLATES / "gateway-copies.yaml").read_text()
STORAGE_TEMPLATE = (TEMPLATES / "local-trial-storage.yaml").read_text()
SIGNING_SECRET_WRITE = (
    "import pathlib,sys; pathlib.Path(sys.argv[1]).write_bytes(sys.stdin.buffer.read())"
)
NEW_SIGNING_SECRET = (
    "import pathlib,secrets; pathlib.Path('/state/django-secret-key')"
    ".write_text(secrets.token_urlsafe(64) + '\\n')"
)
# An absolute path inside a container: its first folder must be a mount.
CONTAINER_PATH = re.compile(r"(?<![\w.$/{}-])/([\w-]+)[^\s\"']*")
# What each `docker compose` action may act on in this guide.
DOCKER_ACTIONS = {"exec": "app", "cp": "app", "restart": "app", "run": "volume-init",
                  "stop": "gateway", "start": "gateway", "logs": "gateway"}


def shell_commands():
    """Every command line in the guide's sh blocks, continuations joined."""
    commands = []
    for block in re.findall(r"^ *```sh\n(.*?)^ *```", GUIDE, re.DOTALL | re.MULTILINE):
        joined = re.sub(r"\\\n\s*", " ", block)
        for line in joined.splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                commands.append(line)
    return commands


COMMANDS = shell_commands()
DOCKER = [line for line in COMMANDS if line.startswith("docker compose ")]
KUBECTL = [line for line in COMMANDS if line.startswith("kubectl ")]


def compose_services():
    """compose.yaml's services: user, command and volume mounts (no YAML package needed)."""
    services, current, key = {}, None, None
    section = None
    for line in COMPOSE.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        text = line.strip()
        if indent == 0:
            section = text.rstrip(":")
            continue
        if section != "services":
            continue
        if indent == 2:
            current = services.setdefault(text.rstrip(":"), {"volumes": []})
            key = None
        elif indent == 4:
            key, _, value = text.partition(":")
            value = value.strip()
            if key == "user":
                current["user"] = value.strip('"')
            elif key == "command" and value.startswith("["):
                current["command"] = json.loads(value)
        elif indent == 6 and key == "volumes" and text.startswith("- "):
            source, _, target = text[2:].rpartition(":")
            if target in ("ro", "rw"):
                source, _, target = source.rpartition(":")
            current["volumes"].append((source, target))
    return services


def compose_volume_names():
    """Docker's name for each named volume: project prefix, or the external name."""
    project = re.search(r"^name: (\S+)$", COMPOSE, re.MULTILINE).group(1)
    block = COMPOSE.split("\nvolumes:\n", 1)[1]
    names, current = {}, None
    for line in block.splitlines():
        if re.match(r"^  \S", line):
            current = line.strip().rstrip(":")
            names[current] = f"{project}_{current}"
        elif current and re.match(r"^    name: ", line):
            names[current] = line.split(":", 1)[1].strip()
    return names


SERVICES = compose_services()


def docker_target(line):
    """The service a `docker compose` line acts on, and any -v mounts it adds."""
    words = line.split()
    action, rest = words[2], words[3:]
    extra = []
    if action == "cp":
        service = next(word.split(":", 1)[0] for word in rest if ":" in word)
        return action, service, extra
    index = 0
    while rest[index].startswith("-"):
        if rest[index] == "-v":
            extra.append(rest[index + 1].strip('"').rsplit(":", 1)[-1])
            index += 2
        else:
            index += 1
    return action, rest[index], extra


def test_bkg01_every_docker_line_names_a_preview_service_and_its_mounts():
    assert DOCKER, "the guide has no Docker preview commands"
    for line in DOCKER:
        action, service, extra = docker_target(line)
        assert DOCKER_ACTIONS.get(action) == service, line
        assert service in SERVICES, f"{service!r} is not a service in compose.yaml: {line}"
        mounts = {target for _, target in SERVICES[service]["volumes"]} | set(extra)
        for match in CONTAINER_PATH.finditer(line):
            top = "/" + match.group(1)
            assert top in mounts, f"{match.group(0)} isn't mounted in {service}: {line}"
        if "manage.py" in line:
            # The preview runs the app's own code from /app, its working folder.
            assert service == "app" and "python manage.py " in line, line


def test_bkg02_every_check_is_shown_for_docker_and_kubernetes():
    def checks(lines):
        return Counter(re.search(r"manage\.py (\w+)", line).group(1)
                       for line in lines if "manage.py" in line)

    in_kubectl, in_docker = checks(KUBECTL), checks(DOCKER)
    assert in_kubectl["verify_restore"] and in_kubectl["check_credentials"]
    # Each Kubernetes check has its Docker form beside it.
    for name, count in in_kubectl.items():
        assert in_docker[name] == count, f"{name}: {in_docker[name]} Docker, {count} Kubernetes"
    for line in KUBECTL:
        if "manage.py" in line:
            assert "python /app/manage.py " in line, line
    assert re.search(r"^WORKDIR /app$", DOCKERFILE, re.MULTILINE)
    assert ("./components/control-plane", "/app") in SERVICES["app"]["volumes"]


def test_bkg03_named_commands_and_flags_exist():
    named = set(re.findall(r"manage\.py (\w+)((?: --?[\w-]+)*)", GUIDE))
    assert named
    commands = get_commands()
    for name, flags in named:
        assert name in commands, f"manage.py {name} isn't a Keeplane command"
        parser = load_command_class(commands[name], name).create_parser("manage.py", name)
        parser.parse_args(flags.split())


def test_bkg04_docker_volume_names_and_owners_match_compose():
    names = compose_volume_names()
    for volume in ("account-data", "provider-keys", "gateway-data"):
        assert f"`{volume}`" in GUIDE
        assert f"`{names[volume]}`" in GUIDE, names[volume]
    for mentioned in re.findall(r"`(keeplane-[\w-]+_[\w-]+)`", GUIDE):
        assert mentioned in names.values(), mentioned
    # The gateway runs as the image's own user; the preview gives /data to it.
    gateway, init = SERVICES["gateway"], SERVICES["volume-init"]
    assert "user" not in gateway
    assert ("gateway-data", "/data") in gateway["volumes"]
    assert ("gateway-data", "/data") in init["volumes"]
    assert init["user"] == "0"
    assert init["command"][0] == "chown" and init["command"][-1] == "/data"
    gateway_owner = init["command"][1]
    restore_chown = [line for line in DOCKER if " chown " in line]
    assert restore_chown, "the guide doesn't give the gateway database back to its user"
    for line in restore_chown:
        assert line.endswith(f"volume-init chown -R {gateway_owner} /data"), line
    app_user = re.findall(r"^USER (\d+):(\d+)$", DOCKERFILE, re.MULTILINE)[-1]
    assert f"UID {app_user[0]}" in GUIDE
    assert f"`{gateway_owner.replace(':', ' ')}`" in GUIDE


def test_bkg05_kubernetes_names_match_the_chart():
    assert re.search(r"kind: Deployment\nmetadata:\n  name: \{\{ \.Release\.Name \}\}-app\n",
                     APP_TEMPLATE)
    assert "app: {{ .Release.Name }}-app" in APP_TEMPLATE
    assert re.search(r"containers:\n\s+- name: app\n", APP_TEMPLATE)
    assert re.search(r"kind: StatefulSet\nmetadata:\n  name: \{\{ \.Release\.Name \}\}-gateway\n",
                     GATEWAY_TEMPLATE)
    for claim in ("state", "provider-keys"):
        assert f"name: {{{{ .Release.Name }}}}-{claim}" in STORAGE_TEMPLATE
        assert f"`<release>-{claim}`" in GUIDE
    for path in ("/state", "/provider-keys"):
        assert f"mountPath: {path}\n" in APP_TEMPLATE
    allowed = {'deploy/"$RELEASE"-app', 'deployment/"$RELEASE"-app',
               'statefulset/"$RELEASE"-gateway', '"$POD"'}
    for line in KUBECTL:
        assert line.startswith('kubectl -n "$NS" '), line
        if " exec " in line:
            assert " -c app " in line, line
            target = line.split(" exec ", 1)[1].replace("-i ", "", 1).split()[0]
            assert target in allowed, line
        if "rollout restart" in line:
            assert line.split("rollout restart ", 1)[1] in allowed, line
        if " get pod " in line:
            assert '-l app="$RELEASE"-app' in line, line
        for match in CONTAINER_PATH.finditer(line):
            assert "/" + match.group(1) in {"/state", "/provider-keys", "/app"}, line


def test_bkg06_paths_in_the_guide_are_the_apps_defaults():
    assert '"/state/keeplane.sqlite3"' in SETTINGS
    assert '"/state/django-secret-key"' in SETTINGS
    assert "/state/keeplane.sqlite3" in GUIDE and "/state/django-secret-key" in GUIDE
    # The Docker preview keeps its database in a folder of its own.
    preview_database = set(re.findall(r"KEEPLANE_SQLITE_PATH: (\S+)", COMPOSE))
    assert preview_database == {"/state/database/keeplane.sqlite3"}
    (path,) = preview_database
    assert f"`{path}` in the `account-data` volume" in GUIDE
    assert [line for line in DOCKER if "keeplane.sqlite3" in line]
    for line in DOCKER:
        if "keeplane.sqlite3" in line:
            assert path in line and "/state/keeplane.sqlite3" not in line, line
    local_config = (ROOT / "integrations/gateway/local.yaml").read_text()
    assert "sqlite:///data/agentgateway.db" in local_config
    assert "/data/agentgateway.db" in GUIDE
    # The trial makes a signing secret only when there is none, as the guide says.
    assert 'p.exists() or p.write_text(' in APP_TEMPLATE
    assert "if not signing_key.exists():" in (ROOT / "deploy/local/prepare_volumes.py").read_text()


def test_bkg07_inline_python_is_the_tested_python(tmp_path):
    snippets = set(re.findall(r'python -c "([^"]+)"', GUIDE))
    assert snippets == {SQLITE_COPY, COPY_IN, SIGNING_SECRET_WRITE, NEW_SIGNING_SECRET}
    # The signing-secret restore writes the backup's bytes into the existing
    # file, so the app keeps owning it with mode 0600.
    secret = tmp_path / "django-secret-key"
    secret.write_text("old\n")
    secret.chmod(0o600)
    kept = b"k" * 86 + b"\n"
    subprocess.run([sys.executable, "-c", SIGNING_SECRET_WRITE, str(secret)],
                   input=kept, check=True, timeout=30)
    assert secret.read_bytes() == kept
    assert secret.stat().st_mode & 0o777 == 0o600


def slug(heading):
    text = re.sub(r"[^\w\- ]", "", heading.strip().lower())
    return text.replace(" ", "-")


def anchors(path):
    return {slug(line.lstrip("#")) for line in path.read_text().splitlines()
            if line.startswith("#")}


def test_bkg08_links_and_anchors_resolve():
    links = re.findall(r"\]\(([^)\s]+)\)", GUIDE)
    assert links
    for link in links:
        if link.startswith("http"):
            continue
        target, _, anchor = link.partition("#")
        path = (GUIDE_PATH.parent / target).resolve() if target else GUIDE_PATH
        assert path.exists(), link
        if anchor:
            assert anchor in anchors(path), link


GATEWAY_WRITE = (
    "import sqlite3,sys; d=sqlite3.connect(sys.argv[1]); "
    "d.execute(\"insert into models values ('again')\"); d.commit(); "
    "print(d.execute('select count(*) from models').fetchone()[0])"
)


@pytest.mark.skipif(not hasattr(os, "geteuid") or os.geteuid() != 0,
                    reason="giving files to the gateway's UID needs root")
def test_bkg09_gateway_restore_leaves_a_file_the_gateway_can_open():
    """The guide's restore as root, then its chown: the gateway's user can write."""
    import shutil
    import sqlite3
    import tempfile

    owner = SERVICES["volume-init"]["command"][1]
    uid, gid = (int(part) for part in owner.split(":"))

    def as_gateway():
        os.setgid(gid)
        os.setuid(uid)

    def gateway_writes(database):
        return subprocess.run([sys.executable, "-c", GATEWAY_WRITE, str(database)],
                              check=False, preexec_fn=as_gateway, capture_output=True,
                              text=True, timeout=30)

    # A folder the gateway's user can reach, like the root of a Docker volume.
    root = Path(tempfile.mkdtemp(prefix="keeplane-gateway-restore-"))
    try:
        root.chmod(0o755)
        backup, data = root / "backup", root / "data"
        backup.mkdir()
        data.mkdir()
        os.chown(data, uid, gid)  # what volume-init does before the gateway starts
        source = sqlite3.connect(backup / "gateway.sqlite3")
        source.execute("create table models (name text)")
        source.execute("insert into models values ('local-fixture')")
        source.commit()
        source.close()
        database = data / "agentgateway.db"
        subprocess.run([sys.executable, "-c", SQLITE_COPY, str(backup / "gateway.sqlite3"),
                        str(database)], check=True, timeout=30)
        assert database.stat().st_uid == 0
        assert gateway_writes(database).returncode != 0
        subprocess.run(["chown", "-R", owner, str(data)], check=True, timeout=30)
        written = gateway_writes(database)
        assert written.returncode == 0, written.stderr
        assert written.stdout.strip() == "2"
    finally:
        shutil.rmtree(root)
