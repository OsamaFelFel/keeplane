# Combined PostgreSQL and CLI sign-in image

**CLIIMAGE-01:** With a prebuilt `postgres-cli-auth-trial` image, run it as UID
65532 with a read-only root against a new PostgreSQL database on an internal
Docker network. Load the native C driver, CFFI and cryptography Rust extension.
Check Toolkit 3.4.1, original driver/wheel
notices and absent Python installers. Apply the actual migrations, register both
fixed public clients twice, and require Gunicorn's database readiness response.
Nothing is installed or copied over the image's app packages. Remove every owned
container, volume and network afterward.

```sh
KEEPLANE_CLI_POSTGRES_IMAGE=keeplane-postgres-cli-trial:local \
  python -m pytest -m live tests/integration/test_cli_postgres_image.py
```

The fixture disables database TLS inside its isolated network. It does not prove
browser/device exchanges, Helm wiring, protected coding, production database
operations or release distribution clearance.
