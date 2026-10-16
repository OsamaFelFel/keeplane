"""Optional real account/key service joined to pinned native token exchange."""

import json

import pytest

from tests.support.personal_dispatch_trial import run_trial


@pytest.mark.live
@pytest.mark.optional
@pytest.mark.infrastructure
def test_real_oauth_personal_key_native_dispatch(tmp_path, report_file):
    report = run_trial(tmp_path / "personal")
    report_file.write_text(json.dumps(report, indent=2))
    assert report.get("passed") and report["cleaned"], (
        "Personal native acceptance failed; inspect safe report"
    )
    assert report["uid"] == 65532 and report["real_validation_contacts"] == 4
    assert report["ordinary_logs_contain_secret"] is False
    assert len(report["checks"]) == 16
