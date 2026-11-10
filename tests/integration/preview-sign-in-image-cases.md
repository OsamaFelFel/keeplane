# Preview image with CLI sign-in

**Edition:** Open Source. Spec 009 ST29, task 009-01, ADR 028.

**PSIMG-01:** Run the image `python3 deploy/local/up.py` builds
(`keeplane-preview:docker-local`, or `KEEPLANE_PREVIEW_IMAGE`) as UID 65532 with
a read-only root and no network. Check that pip and ensurepip are absent, the
CFFI and cryptography Rust extensions load, Django OAuth Toolkit is 3.4.1, every
package in `cli-auth-trial.json` is installed at its recorded version and every
original wheel notice it lists is installed byte for byte. Apply the migrations
to a new SQLite database, register both fixed public CLI clients twice and
require Gunicorn's readiness answer with CLI sign-in on. Nothing is installed or
copied over the image's packages.

```sh
python3 deploy/local/up.py
.venv/bin/python -m pytest tests/integration/test_preview_sign_in_image.py -m live
```

The live-preview workflow runs it after the documented start. It doesn't prove
redistribution clearance: see the
[source and notice obligations](../../components/control-plane/licenses/cli-auth-trial.md).
