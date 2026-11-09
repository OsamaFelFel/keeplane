# The CLI saves the gateway address at sign-in

**Edition:** Open Source and Enterprise. Spec 009 ST30, task 009-02b,
[ADR 030](https://github.com/OsamaFelFel/keeplane-governance/blob/main/adrs/0030-cli-coding-runtime-and-repos.md),
journey DEV-03. A stand-in sign-in server; run
`python -m pytest tests/unit/test_cli_saved_gateway.py`.

The server gives the gateway address as `gateway_url` on `GET /api/runtime/session`
(task 009-02). The CLI checks it with the same rule as `--gateway` and saves it in
the private profile, so `keeplane code` needs no `--gateway`.

| ID | Plain-English action | Expected result |
| --- | --- | --- |
| SG-01 | Sign in through the browser to a server that gives `https://keeplane.example/v1`, the same with a final `/`, or `http://127.0.0.1:5000/v1`. | The profile holds the address without the final `/`, in the `keeplane-credential-v3` format. The folder stays 0700 and its files 0600. |
| SG-02 | Sign in with `--device` to the same server. | The device profile holds the address too, and stays private. |
| SG-03 | Sign in to a server that answers `gateway_url: null`, or an older one with no `gateway_url`. | Nothing is saved for the gateway; the profile keeps the older `keeplane-credential-v2` format, so `keeplane code` says Keeplane doesn't know the gateway address yet. |
| SG-04 | Sign in to a server that gives `http` to another computer, no `/v1`, `/v1/chat/completions`, a query, a user name and password, or a number. | `keeplane login` exits 1, claims no sign-in and prints "The server gave a gateway address the CLI can't use, so you aren't signed in. Ask your admin to check `KEEPLANE_GATEWAY_PUBLIC_URL`." (or "The server returned an invalid account." for the number). It saves no profile, asks the server to end the new sign-in, and prints neither the token nor the address. |
| SG-05 | Run `keeplane refresh` when the server gives an address the profile lacks, a different one, or none. | The profile then holds the server's current address, or none. |
| SG-06 | Save or load a profile whose address isn't exactly the checked form, or a v3 profile without one. | Refused as an invalid profile; the saved one is unchanged. A v2 profile from before this task still loads, with no gateway. The address isn't shown in the credential's printed form. |
| SG-07 | Run `keeplane whoami` after a sign-in that saved an address. | It prints only the account's ID, user name and role. |

`--gateway` still wins over the saved address: see REPO-03 in
[cli-repo-defaults-cases.md](cli-repo-defaults-cases.md).
