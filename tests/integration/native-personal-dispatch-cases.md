# Personal keys through native token exchange

Run `test_native_personal_dispatch.py` only with the separately pinned OAuth
trial image and composed server source. The fixture needs Docker, cached locked
gateway assets and an optional image containing the exact OAuth wheel graph.

| Case | Expected result |
| --- | --- |
| PK-NATIVE-01 | Django's test client drives actual login/CSRF/consent/PKCE views for two OAuth accounts. Real provider validation stores each account's own private, definition-bound key. |
| PK-NATIVE-02 | Native token exchange selects the correct owner's key each time. Caching is off; replacement/removal affects the next call and leaves the other owner unchanged. |
| PK-NATIVE-03 | Logout, disabled/unknown accounts, unknown projects, class withdrawal, wrong stored fingerprint, withdrawn Personal choice and an unreadable private secret deny with zero provider contacts. A changed actual native definition and its fresh reapproval still deny against the old target fingerprint. |
| PK-NATIVE-04 | Forged provider/actor/class/private headers are stripped; only the selected key reaches the provider. No provider key, callback credential or OAuth token appears in runtime responses or ordinary container logs. All owned containers and networks are removed. |
| PK-NATIVE-05 | Repeat the same 18 native requests and four live key validations through the production Django HTTP endpoint. A status-only observer wraps the real WSGI app; no fixture resolves or returns the provider key. |

```sh
KEEPLANE_PERSONAL_DISPATCH_SOURCE=/absolute/composed-source \
KEEPLANE_OAUTH_FIXTURE_IMAGE=sha256:your-cached-optional-image \
python -m pytest -m 'live and optional' tests/integration/test_native_personal_dispatch.py
```

The complete module needs composed source containing the private HTTP adapter
from [#110](https://github.com/OsamaFelFel/keeplane/pull/110). Select
`test_real_oauth_personal_key_native_dispatch` to run the earlier service-only
adapter against an older source.

Both cases use actual Django accounts, records, private files and validation.
The only validator override permits the fixture's loopback synthetic provider.
The first uses a test token endpoint; the second uses the production HTTP view
and middleware. The fixed test routing covers one scalar model; it enables no
installed Personal listener, aliases, fallbacks, replicas or production publication.

Callbacks and administration are loopback-only; the raw LLM/management listener
requires the private operator key. No container port is published. The worker
also drives the native client, so this does not prove an untrusted-client
network boundary, a network browser or a rendered React sign-in. Explicit native
administrator tracing can contain provider keys and developer tokens; this
fixture never enables or proxies that trace. Passing ordinary-log checks does
not claim administrator-trace redaction. Reports and logs stay outside Git.
