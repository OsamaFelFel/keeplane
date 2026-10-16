"""Signal the installed CLI only after its actual native shell child is alive."""

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path


def live(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def process_state(pid):
    try:
        return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
    except FileNotFoundError:
        return "gone"
    except (OSError, IndexError):
        return "unavailable"


def check(
    cli, profile, args, session, repository, environment, execute, status, known, output
):
    root = repository.parent
    record = root / "native-owned.json"
    wrapper = root / "native-control"
    wrapper.write_text(
        f"#!{sys.executable}\nimport os,json,sys\nfrom pathlib import Path\n"
        f"if '--version' not in sys.argv:\n Path({str(record)!r}).write_text(json.dumps({{'pid':os.getpid(),'profile':str(Path(os.environ['HOME']).parent)}}))\n"
        "os.execv('/runtime/opencode',['/runtime/opencode',*sys.argv[1:]])\n"
    )
    wrapper.chmod(0o700)
    barrier = repository / "owned-barrier.py"
    barrier.write_text(
        "import os,json,sys,time\nfrom pathlib import Path\n"
        "root=Path(__file__).parent\nlabel=sys.argv[1]\n"
        "(root/('tool-'+label+'.json')).write_text(json.dumps({'pid':os.getpid(),'group':os.getpgrp()}))\n"
        "for _ in range(1200):\n (root/('heartbeat-'+label)).write_text(str(time.monotonic()))\n time.sleep(.05)\n"
    )
    command = list(args)
    command[command.index("--runtime") + 1] = wrapper
    results = []

    def observation(name, process, native, tool, start, *, timed_out=False):
        result = {
            "signal": name,
            "exit_code": process.poll(),
            "seconds": round(time.monotonic() - start, 3),
            "timed_out": timed_out,
            "native_alive": live(native["pid"]),
            "native_state": process_state(native["pid"]),
            "tool_alive": live(tool["pid"]),
            "tool_state": process_state(tool["pid"]),
            "profile_exists": Path(native["profile"]).exists(),
            "separate_tool_group": tool["group"] != native["pid"],
        }
        results.append(result)
        path = root / "cancellation-result.json"
        path.write_text(json.dumps(results))
        path.chmod(0o600)
        return result

    for name, expected in (("SIGINT", 130), ("SIGTERM", 143)):
        marker = repository / ("tool-" + name + ".json")
        record.unlink(missing_ok=True)
        process = subprocess.Popen(
            list(
                map(
                    str,
                    [
                        cli,
                        "code",
                        "--profile",
                        profile,
                        *command,
                        "--session",
                        session,
                        "CANCEL_" + name,
                    ],
                )
            ),
            env=environment,
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        native = tool = communicated = None
        try:
            deadline = time.monotonic() + 15
            while not marker.exists():
                assert process.poll() is None and time.monotonic() < deadline, (
                    "Owned shell barrier did not start"
                )
                time.sleep(0.05)
            tool = json.loads(marker.read_text())
            native = json.loads(record.read_text())
            assert live(tool["pid"]) and name in status()["started"]
            start = time.monotonic()
            process.send_signal(getattr(signal, name))
            try:
                stdout, stderr = process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                observation(name, process, native, tool, start, timed_out=True)
                raise
            communicated = (stdout, stderr)
            output.append(stdout + stderr)
            result = observation(name, process, native, tool, start)
            assert process.returncode == expected and not any(
                result[key] for key in ("native_alive", "tool_alive", "profile_exists")
            ), "Installed cancellation left an owned child or profile"
        finally:
            if native is None and record.exists():
                native = json.loads(record.read_text())
            if process.poll() is None:
                process.kill()
                process.wait(timeout=2)
            for group in ([native["pid"]] if native else []) + (
                [tool["group"]] if tool else []
            ):
                try:
                    os.killpg(group, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            if communicated is None:
                try:
                    communicated = process.communicate(timeout=1)
                except subprocess.TimeoutExpired:
                    communicated = ("", "Owned cancellation output drain timed out")
            failed = root / "command-failure.json"
            failed.write_text(
                json.dumps(
                    {
                        "command": "cancel-" + name,
                        "stdout": communicated[0],
                        "stderr": communicated[1],
                    }
                )
            )
            failed.chmod(0o600)
            for stream in (process.stdout, process.stderr):
                stream.close()
        execute("refresh-after-" + name, [cli, "refresh", "--profile", profile])
        fresh = json.loads((profile / "credential.json").read_text())
        known.extend([fresh["access_token"], fresh["refresh_token"]])
        (repository / "math.py").write_text("def add(a, b):\n    return a - b\n")
        answer = execute(
            "resume-after-" + name,
            [
                cli,
                "code",
                "--profile",
                profile,
                *args,
                "--session",
                session,
                "RECOVER_" + name,
            ],
        )
        assert any(
            json.loads(line).get("sessionID") == session
            for line in answer.splitlines()
            if line.startswith("{")
        )
        assert (
            repository / "math.py"
        ).read_text() == "def add(a, b):\n    return a + b\n"
    assert status()["recovered"] >= 6
    return fresh, results
