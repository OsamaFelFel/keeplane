"""Public application files stay readable in a non-root image built under umask077."""

import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import uuid

import pytest


ROOT = Path(__file__).resolve().parents[2]
pytestmark = [pytest.mark.live, pytest.mark.infrastructure]


def test_app_image_permissions(report_file):
    assert (ROOT / "components/admin-ui/dist/index.html").is_file(), "Build the admin UI first"
    image = "keeplane-image-permissions-" + uuid.uuid4().hex[:12] + ":test"
    report = {"completed": False, "image_removed": False,
              "permissive_input_file": "common/errors.py (0666)", "runtime_network": "none", "build_dependencies": "cached pinned layers or declared install registry access", "input_file_mode": "0600", "input_directory_mode": "0700"}

    def run(*command, check=True):
        item = subprocess.run(command, cwd=ROOT, capture_output=True, timeout=180)
        if check and item.returncode:
            # The context is public source only; retain build diagnostics privately.
            report["failure_output"] = (item.stderr + item.stdout).decode(errors="replace")[-6000:]
            raise AssertionError(command[0] + " exited " + str(item.returncode))
        return item

    try:
        with tempfile.TemporaryDirectory(prefix="keeplane-image-permissions-") as directory:
            context = Path(directory)
            # Tracked public sources only: never copy ignored credentials or caches.
            tracked = subprocess.check_output([
                "git", "ls-files", "-z", "components/control-plane", "components/admin-ui"
            ], cwd=ROOT).split(b"\0")
            for relative in filter(None, tracked):
                path = Path(relative.decode())
                target = context / path
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / path, target)
            shutil.copytree(ROOT / "components/admin-ui/dist",
                            context / "components/admin-ui/dist")
            for path in context.rglob("*"):
                path.chmod(0o700 if path.is_dir() else 0o600)
            # A permissive builder must not make packaged code writable either.
            (context / "components/control-plane/common/errors.py").chmod(0o666)
            # Preserve the dependency cache; this fixture tests copied application files.
            (context / "components/control-plane/requirements-account-api.txt").chmod(0o644)
            shutil.copyfile(ROOT / "components/control-plane/Dockerfile", context / "Dockerfile")
            run("docker", "build", "--pull=false", "--target", "preview",
                "-t", image, "-f", str(context / "Dockerfile"), str(context))
            probe = '''import json,os,runpy
from pathlib import Path
assert os.getuid()==65532
paths=[p for root in ('/app','/ui') for p in Path(root).rglob('*') if p.is_file()]
assert paths and all(os.access(p,os.R_OK) for p in paths)
assert all(p.stat().st_uid==0 and not os.access(p,os.W_OK) for p in paths)
assert all(p.stat().st_mode & 0o022 == 0 for p in paths)
assert Path('/ui/dist/index.html').read_text().startswith('<!doctype html>')
fonts=list(Path('/ui/dist/fonts').rglob('*'))
assert any(p.is_file() for p in fonts)
runpy.run_path('/app/config/gunicorn.conf.py')
print(json.dumps({'uid':os.getuid(),'public_files_readable':len(paths),'root_owned_and_not_writable':True,'compiled_ui_and_fonts_readable':True,'app_config_loaded':True}))
'''
            report["probe"] = json.loads(run(
                "docker", "run", "--rm", "--network=none",
                "--cap-drop=ALL", image, "python", "-c", probe,
            ).stdout)
            report["completed"] = True
    finally:
        run("docker", "image", "rm", "--force", image, check=False)
        report["image_removed"] = run("docker", "image", "inspect", image, check=False).returncode != 0
        report_file.write_text(json.dumps(report, indent=2) + "\n")
    assert report["completed"] and report["image_removed"]
