"""Preview project CLI migration without changing files or running configured code."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
try:
    import tomllib
except ModuleNotFoundError:
    raise SystemExit("Migration preview requires Python 3.11 or newer for TOML settings.") from None


INSTRUCTIONS = {"AGENTS.md", "CLAUDE.md", "QWEN.md"}
SETTINGS = {
    ".claude/settings.json": {"model", "effortLevel", "permissions", "hooks", "apiKeyHelper", "env"},
    ".claude/settings.local.json": {"model", "effortLevel", "permissions", "hooks", "apiKeyHelper", "env"},
    ".codex/config.toml": {"model", "model_reasoning_effort", "model_providers", "mcp_servers", "sandbox_mode", "approval_policy"},
    ".qwen/settings.json": {"model", "modelProviders", "permissions", "hooks", "mcpServers", "security", "env"},
    ".mcp.json": {"mcpServers"},
}
SKIP = {".git", "node_modules", ".venv", "venv", "__pycache__", ".keeplane", "test-results", "dist", "build"}
LIMIT = 1024 * 1024


class SourceError(ValueError):
    pass


def read_source(root, relative):
    """Open every path component without following links, including during races."""
    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for component in relative.parts[:-1]:
            next_descriptor = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
        source = os.open(relative.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor)
        with os.fdopen(source, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise SourceError("Source must be a regular file.")
            data = stream.read(LIMIT + 1)
            if len(data) > LIMIT:
                raise SourceError("Source exceeds the 1 MiB preview limit.")
            return data
    finally:
        os.close(descriptor)


def preview(directory):
    if os.name != "posix":
        raise ValueError("This prototype supports macOS and Linux.")
    root = Path(directory).expanduser()
    if root.is_symlink():
        raise ValueError("Choose a repository directory, not a symlink.")
    root = root.resolve(strict=True)
    if root == Path.home().resolve() or not (root / ".git").exists():
        raise ValueError("Choose the repository root containing .git; user-home profiles are not scanned.")
    inventory, findings, targets = [], [], {}

    def finding(source, kind, **details):
        findings.append({"source": source, "kind": kind, **details})

    def walk_error(error):
        finding(Path(error.filename).relative_to(root).as_posix(), "unreadable-directory")

    for current, directories, files in os.walk(root, followlinks=False, onerror=walk_error):
        parent = Path(current)
        retained = []
        for name in sorted(directories):
            path = parent / name
            if name in SKIP:
                continue
            if path.is_symlink():
                finding(path.relative_to(root).as_posix(), "skipped-symlink")
            elif (path / ".git").exists():
                finding(path.relative_to(root).as_posix(), "skipped-nested-repository")
            else:
                retained.append(name)
        directories[:] = retained
        for name in sorted(files):
            path = parent / name
            relative = path.relative_to(root)
            short = "/".join(relative.parts[-2:])
            schema = SETTINGS.get(short, SETTINGS.get(name))
            if name not in INSTRUCTIONS and schema is None:
                continue
            source = relative.as_posix()
            entry = {"source": source, "status": "review"}
            inventory.append(entry)
            try:
                data = read_source(root, relative)
                entry["sha256"] = hashlib.sha256(data).hexdigest()
                try:
                    text = data.decode("utf-8")
                except UnicodeError:
                    raise SourceError("Source must use UTF-8 text.") from None
                if name in INSTRUCTIONS:
                    target = relative.with_name("AGENTS.md").as_posix()
                    entry.update(proposed_target=target, treatment="preserve content and directory scope; review before applying")
                    targets.setdefault(target, []).append(entry)
                    continue
                try:
                    config = tomllib.loads(text) if name.endswith(".toml") else json.loads(text)
                except (ValueError, RecursionError):
                    raise SourceError("Malformed TOML." if name.endswith(".toml") else "Malformed JSON.") from None
                if not isinstance(config, dict):
                    raise SourceError("Settings must contain an object.")
                # Values and nested maps can contain credentials. Export only top-level names.
                entry["recognized_fields"] = sorted(config.keys() & schema)
                entry["unknown_fields"] = sorted(config.keys() - schema)
                entry["treatment"] = "keep original settings; native semantics require separate verification"
                for field in entry["recognized_fields"]:
                    if field in {"hooks", "apiKeyHelper", "mcpServers", "mcp_servers", "env", "security"}:
                        finding(source, "do-not-execute-or-import", field=field)
                    else:
                        finding(source, "native-setting-review", field=field)
                if entry["unknown_fields"]:
                    finding(source, "unsupported-settings", fields=entry["unknown_fields"])
            except (OSError, SourceError) as error:
                entry["status"] = "blocked"
                message = str(error) if isinstance(error, SourceError) else "Cannot safely read this source; check permissions and symlinks."
                finding(source, "unreadable-or-malformed-source", message=message)
    for target, entries in targets.items():
        if len({entry["sha256"] for entry in entries}) > 1:
            finding(target, "instruction-conflict", sources=[entry["source"] for entry in entries])
    return {"mode": "preview-only", "inventory": inventory, "findings": findings, "writes": []}


def report(directory):
    try:
        result = preview(directory)
    except (OSError, ValueError):
        print("Cannot scan this path. Choose a readable repository root containing .git, without symlinks.", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 1 if any(entry["status"] == "blocked" for entry in result["inventory"]) or any(
        finding["kind"] == "unreadable-directory" for finding in result["findings"]
    ) else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", nargs="?", type=Path, default=Path.cwd())
    args = parser.parse_args()
    return report(args.directory)


if __name__ == "__main__":
    raise SystemExit(main())
