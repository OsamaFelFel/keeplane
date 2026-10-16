"""Opt-in installation on this preview's managed gateway only."""

import subprocess


def install(repo, runtime, models, port, *, env, wait_ready, app_image=None):
    compose = [
        "docker",
        "compose",
        "--env-file",
        str(runtime / ".env"),
        "-f",
        str(repo / "compose.yaml"),
        "-f",
        str(repo / "deploy/local/runtime.yaml"),
    ]
    environment = dict(env, KEEPLANE_RUNTIME_PORT=str(port))
    if app_image:
        environment.update(
            KEEPLANE_RUNTIME_APP_IMAGE=app_image, KEEPLANE_RUNTIME_OAUTH_ENABLED="1"
        )

    def run(arguments):
        result = subprocess.run(
            compose + arguments,
            cwd=repo,
            env=environment,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        if result.returncode:
            raise RuntimeError("Protected runtime setup did not complete.")
        return result.stdout.strip()

    # Replacing guards while an old request retains a router/backend snapshot
    # is unsupported. Stop the old process before resetting operator files.
    try:
        old = run(["ps", "-q", "gateway"])
        run(["stop", "gateway", "app"])
        run(["run", "--rm", "--no-deps", "runtime-init"])
        run(
            [
                "up",
                "-d",
                "--no-build",
                "--pull",
                "never",
                "--no-deps",
                "--force-recreate",
                "gateway",
            ]
        )
        current = run(["ps", "-q", "gateway"])
        if not current or current == old:
            raise RuntimeError("A fresh managed gateway is required for enrollment.")
        run(
            [
                "run",
                "--rm",
                "--no-deps",
                "runtime-install",
                "python",
                "manage.py",
                "migrate",
                "--noinput",
            ]
        )
        if environment.get("KEEPLANE_RUNTIME_OAUTH_ENABLED") == "1":
            register = [
                "run",
                "--rm",
                "--no-deps",
                "runtime-install",
                "python",
                "manage.py",
                "register_cli_client",
            ]
            run(register)
            run(register + ["--device"])
        run(
            [
                "up",
                "-d",
                "--no-build",
                "--pull",
                "never",
                "--no-deps",
                "--force-recreate",
                "app",
            ]
        )
        wait_ready()
        command = [
            "run",
            "--rm",
            "--no-deps",
            "runtime-install",
            "python",
            "manage.py",
            "install_runtime_guard",
        ]
        for identifier in models:
            command.extend(["--model", identifier])
        run(command)
    except (OSError, subprocess.TimeoutExpired, RuntimeError):
        # Even a failed manifest rollback must not leave a serving endpoint.
        # This targets only the Compose project the operator explicitly started.
        try:
            stopped = subprocess.run(
                compose + ["stop", "gateway"],
                cwd=repo,
                env=environment,
                capture_output=True,
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            raise RuntimeError(
                "Runtime setup failed and stopping its managed gateway could not be confirmed. Stop it before continuing."
            ) from None
        if stopped.returncode:
            raise RuntimeError(
                "Runtime setup failed and stopping its managed gateway could not be confirmed. Stop it before continuing."
            ) from None
        raise RuntimeError(
            "Runtime setup failed; its managed gateway is stopped. Start a fresh instance before trying enrollment again."
        ) from None
    return f"http://127.0.0.1:{port}/v1"
