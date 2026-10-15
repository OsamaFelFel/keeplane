# Runtime project first use

Run `python -m pytest tests/integration/test_runtime_project_use.py` with isolated Django storage.

- An explicit bearer account registers the requested UUID/name and its own usage without onboarding or a class.
- Repeats preserve the original name and class; another account adds its own usage without replacing the first.
- Client user, role, class or access claims, malformed IDs/names and incomplete bodies are rejected without writes.
- Cookie-only and disabled credentials cannot register a project.
- A usage write failure returns 503 and rolls back project creation too.
