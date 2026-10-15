"""A directory bind survives atomic host config replacement in the native gateway."""

import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import uuid

import pytest


ROOT = Path(__file__).resolve().parents[2]
IMAGE = json.loads((ROOT / "deploy/local/stack.lock.json").read_text())["images"][
    "agentgateway"
]
PYTHON_IMAGE = (
    "python@sha256:2d9aefe2fef018a7eb2c13064c89c71929800fd2e5dccdbf52ea5da5bb8d929a"
)
CLIENT = """
import json, os, time, urllib.error, urllib.request
key = os.environ['TRIAL_ADMIN_KEY']
def call(method, path, body=None):
    request = urllib.request.Request('http://127.0.0.1:4000'+path,
        data=None if body is None else json.dumps(body).encode(), method=method,
        headers={'Authorization':'Bearer '+key, 'Content-Type':'application/json'})
    with urllib.request.urlopen(request, timeout=2) as response:
        return response.status, json.load(response)
"""


@pytest.mark.live
@pytest.mark.infrastructure
def test_atomic_config_replacement_keeps_management_working(tmp_path):
    name = "keeplane-config-mount-" + uuid.uuid4().hex[:10]
    token = secrets.token_urlsafe(32)
    config_dir = tmp_path / "config"
    config_dir.mkdir(mode=0o755)
    config = config_dir / "local.yaml"
    content = """config:
  storage: {mode: hybrid}
  database: {url: sqlite:///data/gateway.db}
gateways: {default: {port: 4000}}
ui:
  gateways: default
  policies:
    apiKey:
      mode: strict
      keys:
        - keyHash: HASH
llm:
  models:
    - name: mount-before
      provider:
        custom:
          formats: [{type: completions}]
      params:
        model: unused
        baseUrl: http://127.0.0.1:9/v1
""".replace("HASH", "sha256:" + hashlib.sha256(token.encode()).hexdigest())
    config.write_text(content)
    config.chmod(0o644)

    def command(*args, script=None):
        result = subprocess.run(
            args, input=script, capture_output=True, text=True, timeout=45
        )
        assert result.returncode == 0, result.stderr
        return result.stdout

    def client(script):
        return command(
            "docker",
            "run",
            "--rm",
            "--pull=never",
            "--user",
            "65532:65532",
            "--network",
            "container:" + name,
            "-i",
            "-e",
            "TRIAL_ADMIN_KEY=" + token,
            "-v",
            str(config_dir) + ":/gateway-config:ro",
            PYTHON_IMAGE,
            "python",
            "-",
            script=CLIENT + script,
        )

    try:
        command(
            "docker",
            "run",
            "-d",
            "--pull=never",
            "--name",
            name,
            "--network",
            "none",
            "--tmpfs",
            "/data:rw,uid=65532,gid=65532,mode=700",
            "-v",
            str(config_dir) + ":/gateway-config:ro",
            IMAGE,
            "-f",
            "/gateway-config/local.yaml",
        )
        client("""
for attempt in range(100):
    try:
        status, config = call('GET', '/api/config')
        assert status == 200 and config['llm']['models'][0]['name'] == 'mount-before'
        break
    except (OSError, urllib.error.URLError):
        time.sleep(.1)
else:
    raise AssertionError('Disposable gateway did not become ready')
""")
        replacement = config.with_suffix(".replacement")
        replacement.write_text(content.replace("mount-before", "mount-after"))
        replacement.chmod(0o644)
        os.replace(replacement, config)
        client("""
from pathlib import Path
assert 'mount-after' in Path('/gateway-config/local.yaml').read_text()
status, config = call('GET', '/api/config')
assert status == 200 and config['llm']['models'][0]['name'] == 'mount-after'
path = '/api/config/resources/llm.model'
model = {'name':'mount-write', 'provider':{'custom':{'formats':[{'type':'completions'}]}},
         'params':{'model':'unused', 'baseUrl':'http://127.0.0.1:9/v1'}}
assert call('PUT', path, {'resources':[{'value':model}]})[0] == 200
assert any(row['id'] == 'mount-write' for row in call('GET', path)[1]['resources'])
assert call('DELETE', path+'/mount-write')[0] == 200
assert all(row['id'] != 'mount-write' for row in call('GET', path)[1]['resources'])
""")
    except Exception:
        logs = subprocess.run(
            ["docker", "logs", name], capture_output=True, text=True, timeout=10
        )
        print(logs.stdout + logs.stderr)
        raise
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=30)
