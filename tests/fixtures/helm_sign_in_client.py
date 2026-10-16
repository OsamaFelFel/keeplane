"""Installed-wheel sign-in over a verified test TLS edge."""

import hashlib
import json
import os
import re
import shlex
import ssl
import subprocess
import sys
import time
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import (
    HTTPCookieProcessor,
    HTTPSHandler,
    ProxyHandler,
    Request,
    build_opener,
)
from zipfile import ZipFile

from tests.fixtures.installed_cli_journey import HiddenFields, NoRedirects


class InstalledClient:
    def __init__(self, directory, wheel, ca, origin, username, password):
        self.directory, self.origin = directory, origin
        self.username, self.password = username, password
        self.context = ssl.create_default_context(cafile=str(ca))
        self.opener = build_opener(
            ProxyHandler({}),
            HTTPCookieProcessor(CookieJar()),
            HTTPSHandler(context=self.context),
            NoRedirects(),
        )
        environment = {
            key: value
            for key, value in os.environ.items()
            if key in ("PATH", "LANG", "LC_ALL")
        }
        self.env = dict(
            environment,
            HOME=str(directory),
            SSL_CERT_FILE=str(ca),
            PYTHONUNBUFFERED="1",
            PYTHONNOUSERSITE="1",
            PIP_NO_INDEX="1",
        )
        subprocess.run(
            [sys.executable, "-m", "venv", str(directory / "venv")],
            env=self.env,
            capture_output=True,
            check=True,
            timeout=30,
        )
        python = directory / "venv/bin/python"
        subprocess.run(
            [
                str(python),
                "-m",
                "pip",
                "install",
                "--no-index",
                "--no-deps",
                str(wheel),
            ],
            env=self.env,
            capture_output=True,
            check=True,
            timeout=30,
        )
        self.cli = str(directory / "venv/bin/keeplane")
        installed = subprocess.run(
            [
                str(python),
                "-I",
                "-c",
                "import pathlib,keeplane_cli.keeplane;print(pathlib.Path(keeplane_cli.keeplane.__file__).parent)",
            ],
            env=self.env,
            capture_output=True,
            check=True,
            timeout=10,
        )
        package = Path(installed.stdout.decode().strip())
        assert (directory / "venv") in package.parents
        self.installed_files = 0
        with ZipFile(wheel) as archive:
            for name in archive.namelist():
                if name.startswith("keeplane_cli/") and not name.endswith("/"):
                    assert (
                        package / name.removeprefix("keeplane_cli/")
                    ).read_bytes() == archive.read(name), "Installed wheel bytes differ"
                    self.installed_files += 1
        login = directory / "browser-login.json"
        login.write_text(
            json.dumps({"server": origin, "username": username, "password": password})
        )
        login.chmod(0o600)
        driver = directory / "browser.py"
        driver.write_text(
            "import sys\nfrom tests.fixtures.installed_cli_journey import browser\n"
            "try: browser(sys.argv[1])\nexcept Exception: raise SystemExit(1)\n"
        )
        self.env.update(
            BROWSER=shlex.join([str(python), str(driver), "%s"]),
            KEEPLANE_FIXTURE_LOGIN=str(login),
            PYTHONPATH=str(Path(__file__).resolve().parents[2]),
        )
        self.commands = []
        self.output = []

    def request(
        self, path, data=None, *, expected=200, csrf=None, form=False, method=None
    ):
        from urllib.error import HTTPError

        headers = {"Origin": self.origin}
        payload = None
        if data is not None:
            headers["Content-Type"] = (
                "application/x-www-form-urlencoded" if form else "application/json"
            )
            if not form:
                headers["X-Keeplane-Action"] = "1"
            payload = urlencode(data).encode() if form else json.dumps(data).encode()
        if csrf:
            headers["X-CSRFToken"] = csrf
        try:
            response = self.opener.open(
                Request(self.origin + path, payload, headers, method=method), timeout=8
            )
        except HTTPError as error:
            response = error
        with response:
            assert response.status == expected, "Unexpected fixture browser HTTP status"
            return response.read(65536), response.headers

    def approve_device(self, code):
        raw, _ = self.request("/api/auth-options")
        self.request(
            "/api/session",
            {"username": self.username, "password": self.password},
            csrf=json.loads(raw)["csrf_token"],
        )
        page, _ = self.request(
            "/oauth/confirm-device/?" + urlencode({"user_code": code})
        )
        fields = HiddenFields()
        fields.feed(page.decode())
        fields.values["user_code"] = code
        _, headers = self.request(
            "/oauth/confirm-device/", fields.values, form=True, expected=302
        )
        page, _ = self.request(headers["Location"])
        assert b"Allow CLI access?" in page
        fields = HiddenFields()
        fields.feed(page.decode())
        fields.values["action"] = "accept"
        page, _ = self.request("/oauth/confirm-device/", fields.values, form=True)
        assert b"CLI access allowed" in page

    def command(self, action, profile, *extra, expected=0):
        process = subprocess.run(
            [self.cli, action, "--profile", str(profile), *extra],
            env=self.env,
            capture_output=True,
            timeout=70,
            check=False,
        )
        self.commands.append({"action": action, "exit_code": process.returncode})
        self.output.extend((process.stdout, process.stderr))
        assert process.returncode == expected, "Installed CLI command failed"
        return process.stdout

    def credential_status(self, credential, *, refresh=False):
        from urllib.error import HTTPError

        path, data = "/api/runtime/session", None
        headers = {"Authorization": "Bearer " + credential["access_token"]}
        if refresh:
            path = "/oauth/token/"
            data = urlencode(
                {
                    "grant_type": "refresh_token",
                    "client_id": credential["client_id"],
                    "refresh_token": credential["refresh_token"],
                }
            ).encode()
            headers = {"Content-Type": "application/x-www-form-urlencoded"}
        opener = build_opener(
            ProxyHandler({}), HTTPSHandler(context=self.context), NoRedirects()
        )
        try:
            response = opener.open(
                Request(self.origin + path, data, headers), timeout=8
            )
        except HTTPError as error:
            response = error
        with response:
            response.read(65536)
            return response.status

    def login(self, channel, profile, route):
        arguments = [
            self.cli,
            "login",
            "--server",
            self.origin,
            "--profile",
            str(profile),
            "--timeout",
            "60",
        ]
        if channel == "browser":
            return self.command(
                "login", profile, "--server", self.origin, "--timeout", "60"
            )
        assert channel == "device"
        stdout, stderr = (
            self.directory / "device.stdout",
            self.directory / "device.stderr",
        )
        with stdout.open("wb") as output, stderr.open("wb") as errors:
            process = subprocess.Popen(
                [*arguments, "--device"], env=self.env, stdout=output, stderr=errors
            )
            try:
                deadline = time.monotonic() + 15
                match = None
                while time.monotonic() < deadline:
                    announcement = stdout.read_text().splitlines()
                    if announcement:
                        match = re.fullmatch(
                            r"Open "
                            + re.escape(self.origin)
                            + r"/oauth/confirm-device/ and enter code ([0-9A-V]{8})\.",
                            announcement[0],
                        )
                        break
                    assert process.poll() is None, (
                        "Device client stopped before code approval"
                    )
                    time.sleep(0.05)
                assert match is not None, (
                    "Device client did not announce the expected local verification URL"
                )
                route(
                    1
                )  # Grant starts on copy A; consent and exchange finish on copy B.
                self.approve_device(match.group(1))
                process.wait(timeout=60)
                assert process.returncode == 0 and not stderr.read_bytes(), (
                    "Installed device login failed"
                )
                self.commands.append({"action": "device-login", "exit_code": 0})
            finally:
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=5)
        self.output.extend((stdout.read_bytes(), stderr.read_bytes()))

    @staticmethod
    def credential(profile):
        value = json.loads((profile / "credential.json").read_text())
        assert (profile / "credential.json").stat().st_mode & 0o777 == 0o600
        return value

    @staticmethod
    def digest(value):
        return hashlib.sha256(value.encode()).hexdigest()
