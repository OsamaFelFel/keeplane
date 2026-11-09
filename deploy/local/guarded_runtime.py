"""Install the protected runtime on this preview's managed gateway only.

``deploy/local/up.py`` runs it on every start (ADR 028): it turns on CLI
sign-in, registers the fixed CLI clients, starts a fresh guarded gateway and
then the private model enroller (ADR 027), whose first pass enrols every saved
approval. Naming models enrols exactly those first, as tests do.
"""

import subprocess
import time

# The enroller's own report after each pass (run_model_enroller).
ENROLLER_REPORTS = (
    "No model is enrolled for protected access.",
    "Protected access is ready: ",
    "Protected access is up to date: ",
    "Model enrolment did not complete.",
    "A model change is waiting",
)


def compose_command(repo, runtime):
    return [
        "docker",
        "compose",
        "--env-file",
        str(runtime / ".env"),
        "-f",
        str(repo / "compose.yaml"),
        "-f",
        str(repo / "deploy/local/runtime.yaml"),
    ]


def install(repo, runtime, models, port, *, env, wait_ready):
    compose = compose_command(repo, runtime)
    environment = dict(env, KEEPLANE_RUNTIME_PORT=str(port))

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
        # The enroller writes the guard directory; stop it before the reset.
        run(["stop", "model-enroller", "gateway", "app"])
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
        # The fixed browser and device CLI clients; a changed one is refused.
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
        if models:
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
        # From here the private enroller (ADR 027) keeps the guard in step with
        # saved model changes; neither the app nor the gateway restarts.
        run(
            [
                "up",
                "-d",
                "--no-build",
                "--pull",
                "never",
                "--no-deps",
                "--force-recreate",
                "model-enroller",
            ]
        )
    except (OSError, subprocess.TimeoutExpired, RuntimeError):
        # Even a failed manifest rollback must not leave a serving endpoint.
        # This targets only the Compose project the operator explicitly started.
        try:
            stopped = subprocess.run(
                compose + ["stop", "model-enroller", "gateway"],
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


def enroller_report(repo, runtime, *, env, timeout=90, sleep=time.sleep):
    """The model enroller's first report on this start, or None if none came."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            result = subprocess.run(
                compose_command(repo, runtime)
                + [
                    "--profile",
                    "runtime",
                    "logs",
                    "--no-color",
                    "--no-log-prefix",
                    "model-enroller",
                ],
                cwd=repo,
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            result = None
        if result is not None and not result.returncode:
            for line in result.stdout.splitlines():
                if line.strip().startswith(ENROLLER_REPORTS):
                    return line.strip()
        if time.monotonic() >= deadline:
            return None
        sleep(1)
