"""Installed wheel and actual OAuth/Personal enrollment; synthetic providers."""

import hashlib
from pathlib import Path
from zipfile import ZipFile

import pytest

from tests.e2e.test_installed_cli_journey import ROOT, configured
from tests.fixtures.personal_cli_trial import installed_personal

pytestmark = pytest.mark.optional


def test_installed_personal_keys_tools_refresh_resume_logout(tmp_path):
    source = Path(configured("KEEPLANE_INSTALLED_CLI_SOURCE")).resolve(strict=True)
    app_image = configured("KEEPLANE_INSTALLED_CLI_IMAGE")
    client_image = configured("KEEPLANE_INSTALLED_CLI_CLIENT_IMAGE")
    assert all(
        image.startswith("sha256:") and len(image) == 71
        for image in (app_image, client_image)
    )
    wheel = Path(configured("KEEPLANE_INSTALLED_CLI_WHEEL")).resolve(strict=True)
    assert hashlib.sha256(wheel.read_bytes()).hexdigest() == configured(
        "KEEPLANE_INSTALLED_CLI_WHEEL_SHA256"
    )
    binary = Path(configured("KEEPLANE_OPENCODE_V2_BIN")).resolve(strict=True)
    assert (
        hashlib.sha256(binary.read_bytes()).hexdigest()
        == "a2dee30005064075c216fdcc3fcaba7071c81b39d00b4286206faa50e461b61d"
    )
    with ZipFile(wheel) as package:
        for name in package.namelist():
            if name.startswith("keeplane_cli/"):
                assert (
                    package.read(name)
                    == (
                        source / "components/cli" / name.removeprefix("keeplane_cli/")
                    ).read_bytes()
                )
    for name in (
        "personal_compose.py",
        "personal_provider.py",
        "personal_cli_journey.py",
        "personal_cli_tools.py",
        "personal_cli_provider.py",
        "personal_cli_tls.py",
        "personal_cli_trial.py",
        "installed_cli_journey.py",
        "installed_cli_tls.py",
    ):
        assert (source / "tests/fixtures" / name).read_bytes() == (
            ROOT / "tests/fixtures" / name
        ).read_bytes()
    installed_personal(source, tmp_path, app_image, client_image, wheel, binary)
