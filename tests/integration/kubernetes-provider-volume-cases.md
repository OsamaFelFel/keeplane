# Private provider-key volume

| Case | Required result |
| --- | --- |
| KKEY-01 | Repair a root-owned, permissive PVC for UID 65532 without changing key bytes, names or inodes. The actual private reader succeeds afterward. |
| KKEY-02 | Repeat after group permissions are widened during volume setup. Private reads still succeed with mode 0700/0600. |
| KKEY-03 | Reject managed symlinks, hardlinks, directories and special files. Do not change their targets. Ignore unrelated filenames. |
| KKEY-04 | The chart places the provider-only ownership initializer before the app and SQLite migration containers, keeps account fsGroup, and rejects a managed gateway fsGroup. |

The initializer needs UID 0 with CHOWN, FOWNER and DAC_OVERRIDE to repair an
existing root-owned volume and reopen private files on restart. It mounts only
provider storage, has a read-only root filesystem, drops all other capabilities
and never reads key content. This requires a Restricted Pod Security exception.
An initialization failure keeps the new app container stopped. Existing workers
may temporarily refuse private key reads during volume ownership repair; no
zero-interruption or in-flight dispatch guarantee is claimed.
