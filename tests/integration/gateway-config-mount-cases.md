# Gateway configuration directory mount

Run `python -m pytest tests/integration/test_gateway_config_mount.py -m live` with the pinned gateway and Python images already cached.

- A private native gateway reads its initial configuration.
- Atomically replacing the host file remains visible through the read-only directory mount to both the gateway and a second reader.
- Native configuration reads and a disposable model create/read/delete still work after replacement.
- The fixture has no external network, makes no inference calls and removes its container and temporary database.
