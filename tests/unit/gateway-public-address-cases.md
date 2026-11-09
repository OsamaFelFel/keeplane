# Gateway address for developers' CLIs

**Edition:** Open Source and Enterprise. Spec 009 ST30, task 009-02,
[ADR 030](https://github.com/OsamaFelFel/keeplane-governance/blob/main/adrs/0030-cli-coding-runtime-and-repos.md).
[`test_gateway_public_address.py`](test_gateway_public_address.py) checks the
value of `KEEPLANE_GATEWAY_PUBLIC_URL` that the server reads at start-up. The
installer sets it; Keeplane never works it out from a request.

| ID | Plain-English action | Expected result |
| --- | --- | --- |
| GPA-01 | Leave the setting unset or empty. | Keeplane doesn't know the address: the value is `None`, and the server starts. |
| GPA-02 | Set an HTTPS address ending in `/v1`, with or without a final `/`, a port, upper-case host letters or an IPv6 host. | The server keeps it in the form the CLI uses: lower-case host, no default port, ending in exactly `/v1`. |
| GPA-03 | Set `http://` with this machine as the host (`127.0.0.1`, `localhost`, `[::1]`). | Accepted, as the local preview's `http://127.0.0.1:5000/v1`. |
| GPA-04 | Set `http://` to another computer. | The server refuses to start: the address must use HTTPS unless the gateway is on this machine. |
| GPA-05 | Set a bare host, `/v1/chat/completions`, another path, a query, a fragment, a user name or password, a space, a bad or zero port, or another scheme. | The server refuses to start with a message naming the setting and that the address must end in `/v1`. |
| GPA-06 | Check every accepted address with the CLI's own `--gateway` check. | The CLI accepts it unchanged, so the address the server gives always works for `keeplane code`. |
