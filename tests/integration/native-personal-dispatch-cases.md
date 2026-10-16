# Personal keys through native token exchange

Run `test_native_personal_dispatch.py` only with the separately pinned OAuth
trial image and composed server source. The fixture needs Docker, cached locked
gateway assets and an optional image containing the exact OAuth wheel graph.

| Case | Expected result |
| --- | --- |
| PK-NATIVE-01 | Two actual browser consent/PKCE sign-ins issue distinct OAuth accounts. Real provider validation stores each account's own private, definition-bound key. |
| PK-NATIVE-02 | Native token exchange selects the correct owner's key each time. Caching is off; replacement/removal affects the next call and leaves the other owner unchanged. |
| PK-NATIVE-03 | Logout, disabled/unknown accounts, unknown projects, class withdrawal, wrong stored fingerprint, withdrawn Personal choice and an unreadable private secret deny with zero provider contacts. |
| PK-NATIVE-04 | No provider key, callback credential or OAuth token appears in runtime responses or ordinary container logs. All owned containers and networks are removed. |

```sh
KEEPLANE_PERSONAL_DISPATCH_SOURCE=/absolute/composed-source \
KEEPLANE_OAUTH_FIXTURE_IMAGE=sha256:your-cached-optional-image \
python -m pytest -m 'live and optional' tests/integration/test_native_personal_dispatch.py
```

This uses the actual Django service, records, private files and validator. The
only validator override permits the fixture's loopback synthetic provider.
The token endpoint adapter belongs to the test; no installed Personal route is
enabled. Its per-target model/fingerprint constants cover one scalar model,
not arbitrary aliases, fallbacks, replicas or production publication.

Management and callbacks are unpublished loopback services. Explicit native
administrator tracing can contain provider keys and developer tokens; this
fixture never enables or proxies that trace. Passing ordinary-log checks does
not claim administrator-trace redaction. Reports and logs stay outside Git.
