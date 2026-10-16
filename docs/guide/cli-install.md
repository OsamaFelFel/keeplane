# Install the Keeplane CLI

Use macOS or Linux with Python 3.9+ and `venv`/`pip`. Obtain the Keeplane wheel
from your installation operator and verify its supplied checksum. This trial
wheel contains Keeplane's CLI and instruction plugin; it does not install a
server, coding runtime, model or third-party Python runtime dependency.

```sh
python3 -m venv "$HOME/.local/share/keeplane/venv"
"$HOME/.local/share/keeplane/venv/bin/python" -m pip install \
  --no-index --no-deps /absolute/path/keeplane_cli-0.0.0-py3-none-any.whl
"$HOME/.local/share/keeplane/venv/bin/keeplane" --help
```

The install works offline. Activate the environment to use `keeplane` by name:

```sh
. "$HOME/.local/share/keeplane/venv/bin/activate"
mkdir -p "$HOME/.config/keeplane"
keeplane login --server https://keeplane.example --profile "$HOME/.config/keeplane/account"
keeplane whoami --profile "$HOME/.config/keeplane/account"
```

Use `login --device` if this machine
cannot open a browser. See [sign-in and project commands](cli-project-commands.md),
[device sign-in](cli-device-login.md), [profile recovery](cli-account-profile.md)
and [coding](cli-coding.md). Every source-tree `python3 components/cli/keeplane.py`
command can instead use the installed `keeplane` executable from any directory.
Coding still requires an independently installed OpenCode V2 2.0.27 binary and
an operator-configured protected gateway. The wheel does not select or download
a native runtime, and the server's optional sign-in trial remains separate.
`keeplane init --preview` needs Python 3.11+ for TOML; see the
[read-only migration preview](cli-migration-preview.md).

To replace the trial wheel, stop active CLI commands and install the replacement
with the same interpreter and `--force-reinstall --no-index --no-deps`. Account
profiles and private runtime history live outside this environment. Uninstalling
does not sign out: use `keeplane logout --profile PROFILE` first, then
`python -m pip uninstall keeplane-cli` from the activated environment. If sign-out
cannot be confirmed, follow profile recovery or ask the operator to withdraw it.

## Build a wheel from source

Building needs Python 3.10+ because the pinned build backend requires it. From the
repository root, create a separate build environment:

```sh
python3 -m venv /absolute/private/keeplane-builder
/absolute/private/keeplane-builder/bin/python -m pip install \
  --require-hashes -r components/cli/requirements-build.txt
/absolute/private/keeplane-builder/bin/python -m pip wheel \
  --no-index --no-deps --no-build-isolation --no-cache-dir \
  --wheel-dir /absolute/private/wheels .
```

For an offline build, preload the hash-pinned backend wheel and add
`--no-index --find-links /absolute/private/build-wheels` to the backend install.
Keeplane uses [setuptools 84.0.0](https://pypi.org/project/setuptools/84.0.0/),
unmodified under its [MIT license](https://github.com/pypa/setuptools/blob/v84.0.0/LICENSE),
only while building. Its exact wheel hash is in `requirements-build.txt`; its
original notices remain in that wheel. It is not redistributed in Keeplane's
wheel. Keeplane's wheel retains the repository's complete Apache-2.0 license.

CI builds and installs the wheel without an index, checks its exact contents and
license, and exercises the installed command with a synthetic HTTP issuer. This
does not prove native coding or a deployed sign-in server. No package-index
publication, automatic update or release versioning is introduced here.
