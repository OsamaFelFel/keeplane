"""Isolated checks for the infrastructure-managed first admin."""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "components/control-plane"))
from local_identity import IdentityError, LocalIdentity
from audit import AuditStore


def main():
    results = []
    with tempfile.TemporaryDirectory(prefix="keeplane-identity-") as temp:
        root = Path(temp)
        secret = root / "first-admin-password"
        secret.write_text("first-test-password-123\n")
        database = root / "accounts.sqlite3"
        audit = AuditStore(root / "audit.sqlite3")
        identity = LocalIdentity(database, secret, audit)
        token = identity.login("first-admin", "first-test-password-123")
        listed = identity.users({"search": ["first-admin"]})["users"]
        first = listed[0]
        results.append({"id": "ACCT-21", "verdict": "pass" if
                        identity.session(token)["role"] == "admin" and len(listed) == 1 and
                        first["managed"] and first["sign_in"] == "break-glass" else "fail"})

        secret.write_text("new-test-password-456\n")
        restarted = LocalIdentity(database, secret, audit)
        old_password_refused = False
        try:
            restarted.login("first-admin", "first-test-password-123")
        except IdentityError as error:
            old_password_refused = error.status == 401
        new_token = restarted.login("first-admin", "new-test-password-456")
        results.append({"id": "ACCT-22", "verdict": "pass" if
                        restarted.session(token) is None and old_password_refused and
                        restarted.session(new_token)["role"] == "admin" else "fail"})

    print(json.dumps({"results": results}))
    if any(row["verdict"] != "pass" for row in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
