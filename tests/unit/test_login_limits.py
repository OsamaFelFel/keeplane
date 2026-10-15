"""Shared sign-in budgets, recovery, and fail-closed storage behavior."""

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "components/control-plane"))
from audit import AuditStore
from local_identity import IdentityError, LocalIdentity, LOGIN_ATTEMPTS, LOGIN_WINDOW_SECONDS


class LoginLimitTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.secret = self.root / "first-admin-password"
        self.secret.write_text("first-test-password-123\n")
        self.audit = AuditStore(self.root / "audit.sqlite3")
        self.identity = LocalIdentity(self.root / "accounts.sqlite3", self.secret, self.audit)
        self.clock = patch("local_identity.time.time", return_value=1000).start()
        self.addCleanup(patch.stopall)

    def rejected(self, username="first-admin", password="wrong-password"):
        with self.assertRaises(IdentityError) as caught:
            self.identity.login(username, password)
        return caught.exception

    def exhaust(self, username="first-admin"):
        for _ in range(LOGIN_ATTEMPTS):
            self.assertEqual(self.rejected(username).status, 401)

    def test_ll_01_known_and_unknown_accounts_have_the_same_budget(self):
        for username in ("first-admin", "missing-user"):
            self.exhaust(username)
            error = self.rejected(username)
            self.assertEqual((error.status, error.retry_after), (429, LOGIN_WINDOW_SECONDS))
        with self.identity.connect() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM sessions").fetchone()[0], 0)
        self.assertEqual(self.audit.records()["total"], 0)

    def test_ll_02_case_changes_and_restart_do_not_reset_the_budget(self):
        self.exhaust()
        self.identity = LocalIdentity(self.identity.database, self.secret, self.audit)
        self.assertEqual(self.rejected("FIRST-ADMIN").status, 429)

    def test_ll_03_window_expires_and_a_valid_password_recovers(self):
        self.exhaust()
        self.clock.return_value = 1000 + LOGIN_WINDOW_SECONDS - 1
        self.assertEqual(self.rejected().retry_after, 1)
        self.clock.return_value += 1
        token = self.identity.login("first-admin", "first-test-password-123")
        self.assertEqual(self.identity.session(token)["role"], "admin")
        with self.identity.connect() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM login_attempts").fetchone()[0], 0)

    def test_ll_04_success_resets_earlier_failures(self):
        for _ in range(LOGIN_ATTEMPTS - 1):
            self.assertEqual(self.rejected().status, 401)
        self.identity.login("first-admin", "first-test-password-123")
        self.exhaust()
        self.assertEqual(self.rejected().status, 429)

    def test_ll_05_parallel_workers_share_the_password_check_budget(self):
        def attempt(index):
            return self.rejected("FIRST-ADMIN" if index % 2 else "first-admin").status
        with patch("local_identity.password_matches", return_value=False) as check:
            with ThreadPoolExecutor(max_workers=8) as executor:
                statuses = list(executor.map(attempt, range(8)))
        self.assertEqual(statuses.count(401), LOGIN_ATTEMPTS)
        self.assertEqual(statuses.count(429), 8 - LOGIN_ATTEMPTS)
        self.assertEqual(check.call_count, LOGIN_ATTEMPTS)

    def test_ll_06_storage_failure_never_creates_a_session(self):
        with self.identity.connect() as db:
            db.execute("DROP TABLE login_attempts")
        self.assertEqual(self.rejected(password="first-test-password-123").status, 503)
        with self.identity.connect() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM sessions").fetchone()[0], 0)

    def test_ll_07_credential_rotation_clears_only_the_break_glass_budget(self):
        self.exhaust()
        self.exhaust("missing-user")
        self.secret.write_text("new-first-admin-password-456\n")
        self.identity = LocalIdentity(self.identity.database, self.secret, self.audit)
        token = self.identity.login("first-admin", "new-first-admin-password-456")
        self.assertEqual(self.identity.session(token)["role"], "admin")
        self.assertEqual(self.rejected("missing-user").status, 429)

    def test_ll_08_expired_buckets_are_pruned(self):
        self.rejected("missing-user")
        self.clock.return_value += LOGIN_WINDOW_SECONDS
        self.rejected("another-user")
        with self.identity.connect() as db:
            rows = db.execute("SELECT bucket, attempts FROM login_attempts").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertNotIn("another-user", rows[0]["bucket"])


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(LoginLimitTests)
    tests = list(suite)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    failed = {test.id() for test, _ in result.failures + result.errors + result.skipped}
    print(json.dumps({"results": [
        {"id": "LL-" + test.id().split("test_ll_")[1][:2],
         "verdict": "fail" if test.id() in failed else "pass"} for test in tests]}))
    raise SystemExit(0 if result.wasSuccessful() else 1)
