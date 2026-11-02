# Managed provider key availability

Run `python -m pytest tests/unit/test_provider_key_availability.py`.
These check the read of a server-managed shared provider key file inside
`PROVIDER_KEY_DIR`. The check reports only whether the key is usable; it never
returns the key.

| Case | Expected result |
| --- | --- |
| PKA-01 Valid key, then the file is removed | Available, then unavailable. |
| PKA-02 Key with storage-accepted padding or UTF-8 | Available. |
| PKA-03 Empty, short, oversized, newline, NUL, invalid UTF-8 or blank key | Unavailable. |
| PKA-04 Path outside the folder, `..`, symbolic link, directory, FIFO, relative folder, unmanaged name or a linked folder | Unavailable; nothing outside key storage is read. |
| PKA-05 Key file with mode 0, as a non-root user | Unavailable. Under root this case is skipped with a reason that names root, because root reads a file whatever its mode. |
| PKA-06 Key file whose open is refused with a permission error, for every user | Available before the refusal, unavailable after it. This is the root-safe form of PKA-05: the same `PermissionError` at the same file-open call. |
| PKA-07 The forced refusal is exact | Opening that key by absolute path or through its folder gives the same permission error a non-root user gets; another key file in the folder stays available. |
