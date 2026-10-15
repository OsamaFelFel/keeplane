"""Explicit report paths work when tests are packaged at /tests in a container."""

import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("reporting", Path(__file__).resolve().parents[1] / "e2e/reporting.py")
reporting = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reporting)


class ReportDirectory(unittest.TestCase):
    def test_override_does_not_require_a_repository_parent(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp) / "new/reports"
            with patch.object(reporting, "__file__", "/tests/reporting.py"), \
                    patch.dict(os.environ, {"KEEPLANE_TEST_REPORT_DIR": str(directory)}):
                report = reporting.report_path("result.json")
            self.assertEqual(report, directory / "result.json")
            self.assertTrue(directory.is_dir())


if __name__ == "__main__":
    unittest.main()
