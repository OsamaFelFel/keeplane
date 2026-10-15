# Gateway database Secret, rotation and recovery

**Edition:** Open Source · **Environment:** local Docker, `kind-keeplane` and the separate Calico/TLS fixture

The managed and separately installed gateway values now keep only a database
password placeholder. Each local PostgreSQL fixture and gateway reads its own
namespaced Secret. Setup generates stable password files with owner-only access;
it refuses an automatic replacement of a legacy database or a password file
that does not match the existing Secret. No component versions or dependencies
changed.

The [focused five-case run](https://github.com/OsamaFelFel/keeplane/blob/de0aba5f8052fbbec55a2060309812812f09588e/tests/e2e/runs/2026-10-12-database-secret-focused.json) passed:
missing credentials prevent gateway startup; correct credentials start two
replicas without a password in the ConfigMap or Helm manifest; a registered
model answers on both replicas; rotating the database role and Secret replaces
both gateway pods, refuses the old password and preserves model calls; and a
database backup restores the saved model after replacing the temporary database.
The disposable test namespace was removed.

The [running preview migration](https://github.com/OsamaFelFel/keeplane/blob/de0aba5f8052fbbec55a2060309812812f09588e/tests/e2e/runs/2026-10-12-database-secret-preview-migration.json)
preserved all eight managed models and all three supplied-gateway models through
private backups and restores. Both fixtures still answered. The managed gateway
returned to two Ready replicas and the supplied gateway to one. The setup's
credential-match guard then passed against both live installations. The
[render diagnostic](https://github.com/OsamaFelFel/keeplane/blob/de0aba5f8052fbbec55a2060309812812f09588e/tests/e2e/runs/2026-10-12-database-secret-package-diagnostic.json) no longer
finds a literal password in the rendered gateway ConfigMap.

The [complete Docker/kind regression](https://github.com/OsamaFelFel/keeplane/blob/de0aba5f8052fbbec55a2060309812812f09588e/tests/e2e/runs/2026-10-12-database-secret-full-regression.json)
passed 52/52 suites and 312/312 cases. It includes the new packaging and database
cases, accounts, Data Classes, Audit, local and cloud model management, provider
key rotation, customer-run gateway behavior, replica failure, and real Qwen
runtime checks. Both previews' original Data Classes settings were restored.
Python compilation, shell syntax and diff checks passed. A scan of changed files
found no raw or base64 copies of the live preview credentials. UI code and
dependency versions were unchanged by this slice.

The [managed TLS/Calico repeat](https://github.com/OsamaFelFel/keeplane/blob/de0aba5f8052fbbec55a2060309812812f09588e/tests/e2e/runs/2026-10-12-database-secret-managed-edge-final.json)
passed 11/11 cases, including a model answer with one gateway replica stopped
and model-catalog readback after recovery. The
[existing-gateway TLS/Calico run](https://github.com/OsamaFelFel/keeplane/blob/de0aba5f8052fbbec55a2060309812812f09588e/tests/e2e/runs/2026-10-12-database-secret-existing-edge.json)
passed 5/5 cases, including preflight, protected registration and model calls,
and refusal of an unrelated pod. Their disposable namespaces were removed.
The first recorded managed edge run stopped because its temporary gateway key
hash files were absent; the [failed result](https://github.com/OsamaFelFel/keeplane/blob/de0aba5f8052fbbec55a2060309812812f09588e/tests/e2e/runs/2026-10-12-database-secret-managed-edge.json)
is retained. Its isolated kubeconfig and hash files were restored, and the
current preview image was loaded before repeating the check.

These tests use disposable PostgreSQL storage and local fixed-answer model
fixtures. They do not prove uninterrupted credential rotation, production
database availability, backup policy, cluster encryption, Secret access control,
provider-key delivery to a separate gateway, or a licensed release gateway.
The chart remains a preview.
