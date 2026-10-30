# Installed Personal-key CLI cycle

This optional case uses the installed Keeplane wheel, actual browser sign-in,
admin model registration, managed installer, protected native gateway and pinned
OpenCode V2. Both OpenAI and Anthropic providers are synthetic HTTPS services;
their key/header checks run before any tool responder. No paid model is called.

| Case | Required result |
| --- | --- |
| PCLI-01 | Offline wheel/native hashes match; reviewed CLAUDE.md copy supplies exact instruction bytes/hash to model requests. |
| PCLI-02 | Both accounts sign in through actual consent, register use and see both allowed Personal model IDs. |
| PCLI-03 | Missing key reports missing; both allowed models need the developer's own key, so no other model can take the task and coding displays “Add or replace your provider key” and denies within ten seconds without hitting the runtime deadline, with provider contacts, probes, tools and failures all unchanged. |
| PCLI-04 | Stdin-only key set/status precedes actual read/edit tools for the selected provider and owner. |
| PCLI-05 | Replacement selects the new key immediately; credential refresh and new-process resume preserve exact completed tool-call/result pairs. |
| PCLI-06 | Other-owner key metadata stays separate; neither account can use the other's saved history, even with the same allowed project/model. |
| PCLI-07 | Removal reports missing; with no other usable model, coding displays “Add or replace your provider key” and denies within ten seconds without a runtime timeout, leaving all provider counters unchanged; the other owner still runs tools. Both remove their keys and sign out; logged-out bearer returns 401 with unchanged provider state. |
| PCLI-08 | Developer uses a separate internal network, UID 65532 and read-only root; no server/key/private-TLS volume is mounted. Wrong CA fails and retained history/output contains no credential/key bytes. |

Use a frozen Git checkout containing the actual Personal activation, admin
registration, reusable `PersonalCompose` fixture and this test's exact files.
Configure the same explicit artifact variables as the
[installed shared-key cycle](installed-cli-cases.md), plus
`KEEPLANE_INSTALLED_CLI_CLIENT_IMAGE` for the cached native-capable client image.
Then run:

```sh
python -m pytest -q -m optional tests/e2e/test_installed_personal_cli.py
```

The host bootstrap uses owned loopback ports on its ordinary bridge. After it
validates and installs, only a fixed TLS front joins that bridge and the client's
separate internal network. It forwards account port 3000, protected port 5000 and
only GET /fixture/status from the provider. The observation port refuses other
paths/methods and does not forward client headers. It never forwards raw port
4000 or private admin port 15000. Keys reach the client
worker only through private stdin and remain in memory until uploaded through
the unchanged own-key API. Public CA material is the client's only TLS mount.

Keep reports outside Git. Cleanup is required on success and failure. This is a
controlled installed integration trial, not final runtime/distribution approval,
complete onboarding or a Personal interruption guarantee. The separate
[migration/cancellation case](installed-cli-cases.md) covers foreground interruption
with shared-key coding.
