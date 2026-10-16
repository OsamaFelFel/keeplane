"""Actual installed wrapper/native shell cancellation and credential-bound recovery."""

import pytest

from tests.e2e.test_installed_cli_journey import installed_trial

pytestmark = pytest.mark.optional


def test_installed_sigint_sigterm_shell_cleanup_and_resume(tmp_path):
    installed_trial(tmp_path, cancellation=True)
