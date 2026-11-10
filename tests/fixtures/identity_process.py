"""One control-plane process, as one app copy, for the identity replica cases.

It reads one JSON command per line on stdin and answers with one JSON line, so
a test can keep two copies open on one database and send a browser's cookies
to either of them. Requests go through Django's full middleware stack with CSRF
checks enforced, as a browser's requests do; cookies stay with the test.
"""

import hashlib
import json
import os
import threading
import time

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from django.apps import apps
from django.core import serializers
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import Client
from django.urls import URLPattern, URLResolver, get_resolver
from django.urls.resolvers import RoutePattern

# Values that fill each path converter; none names a real record.
SAMPLE = {
    "str": "unknown",
    "uuid": "00000000-0000-4000-8000-000000000000",
    "int": "1",
    "slug": "unknown",
    "path": "unknown",
}
# The two regular-expression routes, which have no converters to fill.
REGEX_SAMPLES = {
    "asset": ["app/assets/missing.js"],
    "application": ["", "app/", "users"],
}


def migrate():
    executor = MigrationExecutor(connection)
    executor.migrate(executor.loader.graph.leaf_nodes())
    return {"migrated": True}


def http(command):
    """One request from a browser holding the given cookies."""
    client = Client(enforce_csrf_checks=True, HTTP_HOST="127.0.0.1")
    for name, value in command.get("cookies", {}).items():
        client.cookies[name] = value
    headers = command.get("headers", {})
    method, path = command["method"], command["path"]
    if method == "GET":
        response = client.get(path, headers=headers)
    else:
        response = client.generic(
            method,
            path,
            json.dumps(command.get("body", {})),
            content_type="application/json",
            headers=headers,
        )
    try:
        body = response.json()
    except ValueError:
        body = None
    return {
        "status": response.status_code,
        "body": body,
        "retry_after": response.get("Retry-After"),
        # A deleted cookie comes back empty: the browser drops it.
        "cookies": {name: morsel.value for name, morsel in response.cookies.items()},
    }


def burst(command):
    """Send several sign-ins at once from separate threads and connections.

    Every thread waits for the same wall-clock moment, so two copies given the
    same moment send their requests together.
    """
    statuses = [None] * len(command["attempts"])

    def send(index, attempt):
        try:
            delay = command["start_at"] - time.time()
            if delay > 0:
                time.sleep(delay)
            statuses[index] = http(
                {
                    "method": "POST",
                    "path": "/api/session",
                    "cookies": command["cookies"],
                    "headers": command["headers"],
                    "body": attempt,
                }
            )["status"]
        finally:
            connection.close()

    threads = [
        threading.Thread(target=send, args=(index, attempt))
        for index, attempt in enumerate(command["attempts"])
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return {"statuses": statuses}


def concrete(route):
    """A request path for a route pattern, with every converter filled in."""
    text = str(route)
    for name, value in SAMPLE.items():
        while f"<{name}:" in text:
            start = text.index(f"<{name}:")
            text = text[:start] + value + text[text.index(">", start) + 1 :]
    if "<" in text:
        raise ValueError(f"Add a sample value for the route {route}")
    return text


def routes():
    """Every route Keeplane serves, read from Django's URL table itself."""
    found = []

    def walk(patterns, prefix):
        for entry in patterns:
            if isinstance(entry, URLResolver):
                walk(entry.url_patterns, prefix + concrete(entry.pattern))
                continue
            assert isinstance(entry, URLPattern)
            callback = entry.callback
            name = callback.__module__ + "." + callback.__name__
            if isinstance(entry.pattern, RoutePattern):
                paths = [prefix + concrete(entry.pattern)]
            else:
                if callback.__name__ not in REGEX_SAMPLES:
                    raise ValueError(f"Add sample paths for the route {entry.pattern}")
                paths = [prefix + path for path in REGEX_SAMPLES[callback.__name__]]
            for path in paths:
                found.append(
                    {
                        "path": "/" + path,
                        "view": name,
                        "bearer_only": bool(
                            getattr(callback, "runtime_bearer_only", False)
                        ),
                    }
                )

    walk(get_resolver().url_patterns, "")
    return {"routes": found}


def snapshot():
    """A digest of every stored row, to show that refused requests changed nothing."""
    digest = hashlib.sha256()
    counts = {}
    for model in sorted(apps.get_models(), key=lambda model: model._meta.label):
        rows = model._default_manager.order_by("pk")
        counts[model._meta.label] = rows.count()
        digest.update(model._meta.label.encode())
        digest.update(serializers.serialize("json", rows).encode())
    return {"digest": digest.hexdigest(), "counts": counts}


def stored():
    from accounts.models import LoginBudget
    from audit.models import AuditRecord
    from django.contrib.sessions.models import Session

    return {
        "sessions": Session.objects.count(),
        "break_glass_records": AuditRecord.objects.filter(
            kind="break_glass_sign_ins"
        ).count(),
        "budgets": sorted(LoginBudget.objects.values_list("attempts", flat=True)),
    }


ACTIONS = {
    "migrate": lambda command: migrate(),
    "http": http,
    "burst": burst,
    "routes": lambda command: routes(),
    "snapshot": lambda command: snapshot(),
    "stored": lambda command: stored(),
}


def main():
    import sys

    for line in sys.stdin:
        try:
            command = json.loads(line)
            answer = {"ok": True, "result": ACTIONS[command["action"]](command)}
        except Exception as error:  # noqa: BLE001 - report fixture failures to the test.
            answer = {"ok": False, "error": type(error).__name__ + ": " + str(error)}
        finally:
            connection.close()
        print(json.dumps(answer), flush=True)


if __name__ == "__main__":
    main()
