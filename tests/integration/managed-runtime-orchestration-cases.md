# Managed host orchestration

This opt-in check runs the actual `guarded_runtime.install()` subprocess flow.
It does not run `up.py.main()`, download models, build images or retire an older
preview. Use an immutable cached OAuth app image and a source snapshot containing
the real issuer, stable model writer and installed CLI fixture dependencies:

```sh
KEEPLANE_ORCHESTRATION_SOURCE=/absolute/source/snapshot \
KEEPLANE_INSTALLED_CLI_IMAGE=sha256:IMAGE_DIGEST \
KEEPLANE_TEST_REPORT_DIR=/private/tmp/owned-runtime-report \
pytest tests/integration/test_managed_runtime_orchestration.py -m live
```

The fixture copies that source into a private repository directory. Its base
Compose topology has only a gateway, app, synthetic provider and initialization
job. All volumes are local to a unique `COMPOSE_PROJECT_NAME`; a rendered-config
check rejects the fixed external preview account volume before any container
starts. Its project-owned bridge matches local Compose; this check does not prove
egress isolation. Host ports are reserved loopback ports. The actual runtime override,
launcher, private preparation scripts, migrations, client registration and
management installer are unchanged. The fixture supplies `/app` as the working
directory, runs the real Gunicorn configuration and includes `/opt/oauth` on
Python's module path for the cached OAuth test image.

The cases use real admin HTTP model registration, real browser PKCE sign-in and
a guarded provider request. Re-enrollment must preserve credentials, accounts,
model approval and the current OAuth grant. A forced missing-model enrollment
must stop the owned gateway while its app/provider keep running, with no extra
provider contact. The failing subprocess must be the actual enrollment command,
followed by a successful stop of only that gateway. Safe stages/statuses and exact source/file hashes are saved
before cleanup; the JSON report omits credentials, request content and raw logs.
On failure, owned container logs are retained separately in a private directory
with owner-only file permissions for diagnosis.
All owned containers, networks and volumes are removed afterward.
