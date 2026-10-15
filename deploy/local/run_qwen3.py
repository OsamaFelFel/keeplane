"""Run the pinned Qwen3 4B local preview model with llama.cpp on this host."""

import argparse
import hashlib
import os
from pathlib import Path
import subprocess


MODEL_SHA = "2fde00ce69dd4899c70d020845e2638353015bba0fdf161b3eb965f2bca4464e"
RUNNER_COMMIT = "3d65c90d04d337e88f2b1f7f0061f40a5324e662"


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as file:
        for chunk in iter(lambda: file.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runner-binary", type=Path, required=True,
                        help="llama-server built from the pinned llama.cpp source")
    parser.add_argument("--model-file", type=Path, required=True)
    args = parser.parse_args()
    runner = args.runner_binary.resolve(strict=True)
    model = args.model_file.resolve(strict=True)
    if sha256(model) != MODEL_SHA:
        parser.error("The model file does not match the pinned Qwen3 4B artifact")
    try:
        commit = subprocess.check_output(["git", "-C", str(runner.parents[2]),
                                          "rev-parse", "HEAD"], text=True).strip()
    except subprocess.CalledProcessError:
        parser.error("The runner binary is not inside the pinned llama.cpp checkout")
    if commit != RUNNER_COMMIT:
        parser.error("The runner source commit differs from the tested build")
    command = [str(runner), "-m", str(model), "--jinja",
               "--alias", "qwen3-4b-instruct", "--host", "127.0.0.1",
               "--port", "14424", "--ctx-size", "12288", "-n", "512", "-t", "6"]
    os.execv(str(runner), command)


if __name__ == "__main__":
    main()
