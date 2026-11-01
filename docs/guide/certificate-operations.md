# Check and renew certificates

A Kubernetes installation of Keeplane relies on up to four certificates. This
page shows how to see when each one expires, how to renew or replace it, and
what people notice if one expires. It applies to the Helm chart in
`deploy/helm/keeplane` in PostgreSQL mode; see the
[Kubernetes installation reference](kubernetes-installation-reference.md) for
the rest of the install.

| Certificate | Kept in | Who checks it | When a renewal takes effect |
| --- | --- | --- | --- |
| Public HTTPS certificate | Secret `ingress.tlsSecretName` (`tls.crt`, `tls.key`) | Browsers and developers' CLIs, through your ingress controller | When your ingress controller reloads the Secret, usually within seconds; Keeplane does not restart |
| PostgreSQL server certificate | Your database server | App copies and the migration Job, with `verify-full` against the database CA | On the database's next new connection; each app request opens one |
| Database CA | Secret `app.postgres.caSecret` (`ca.crt`) | App copies and the migration Job | On the next database connection, no restart |
| Customer-run gateway's certificate and CA (existing mode with an `https` address) | The gateway's own installation; the CA in Secret `gateway.caSecret` (`ca.crt`) | App copies and the preflight Job | On the next gateway call, no restart |

The managed gateway copies are reached inside the cluster over plain HTTP on
port 4000, protected by the [gateway access keys](kubernetes-installation-reference.md#gateway-access-keys)
and, where your cluster enforces it, the gateway NetworkPolicy. They have no
certificate to renew. Keeplane never creates or renews a certificate itself.

## Before you start

- `kubectl` access to the release namespace. Reading, creating and updating
  Secrets needs the example
  [installer Role](kubernetes-namespace-permissions.md#installer-role).
  Running `check_credentials` with `kubectl exec` in the app pods needs
  `pods/exec`, which only the optional
  [operations Role](kubernetes-namespace-permissions.md#operations-role)
  grants ([which Role each command needs](kubernetes-namespace-permissions.md#which-role-each-command-needs)).
- `openssl` on your workstation.
- The certificate and key you are installing, as PEM files.

Set your namespace and release once:

```sh
NS=<namespace>; RELEASE=<release>
```

## See every expiry date at once

`check_credentials` reports the certificates Keeplane itself checks: every
certificate in the mounted database CA file, the certificate the PostgreSQL
server presents, and, with a customer-run `https` gateway, every certificate in
the mounted gateway CA file and the certificate each gateway copy presents. It
shows each one's subject, issuer, SHA-256 fingerprint, expiry date and days
left. It never prints a key or password.

```sh
kubectl -n "$NS" exec deploy/"$RELEASE"-app -c app -- \
  python /app/manage.py check_credentials > report.json
jq '{certificates, certificate_problems, certificate_warnings}' report.json
```

Expected result on a healthy installation: `"certificate_problems": []` and
`"passed": true`. A certificate's `status` is one of:

| `status` | Meaning | Effect on the check |
| --- | --- | --- |
| `valid` | More than 30 days left | None |
| `expires soon` | 30 days or fewer left; listed under `certificate_warnings` | Still passes. Renew it now |
| `expired` | Past its expiry date; listed under `certificate_problems` | Fails, exit status 1 |
| `not yet valid` | Its start date is in the future, usually a clock problem | Fails |

A server certificate also shows `"trusted"`. `false` fails the check and the
`problem` says why, for example `certificate has expired`, `unable to get local
issuer certificate` (the mounted CA does not cover it) or `the certificate does
not match <host>`. The expiry date is still shown, read without trusting it.

To warn earlier, for example 60 days ahead, add
`--certificate-warning-days 60`. The check only reads; run it as often as
you like, for example from your monitoring, and alert when `passed` is false or
`certificate_warnings` is not empty.

The public HTTPS certificate is served by your ingress controller, not by
Keeplane, so check it directly:

```sh
kubectl -n "$NS" get secret <tls-secret> -o jsonpath='{.data.tls\.crt}' \
  | base64 -d | openssl x509 -noout -subject -enddate
openssl s_client -connect <keeplane-host>:443 -servername <keeplane-host> </dev/null 2>/dev/null \
  | openssl x509 -noout -subject -enddate
```

The second command shows what is actually served. If its date differs from
the Secret's, the controller has not loaded the new certificate yet.

## Renew the public HTTPS certificate

The Ingress only names the Secret; Helm refuses `ingress.enabled` without
`ingress.tlsSecretName`, and the chart never renders the Secret itself. Replace
the Secret's contents in place and keep its name, so no Helm upgrade is needed:

```sh
kubectl -n "$NS" create secret tls <tls-secret> --cert=fullchain.pem --key=privkey.pem \
  --dry-run=client -o yaml | kubectl -n "$NS" apply -f -
```

`fullchain.pem` holds the server certificate followed by any intermediate
certificates. Its names must include `ingress.host`. Expected result: within a
few seconds the `openssl s_client` command above shows the new expiry date.
Sessions, CLI sign-ins and model calls continue; nobody is signed out.

**cert-manager.** Because the chart only references the Secret, cert-manager
can fill it. Create a cert-manager `Certificate` in the release namespace with
`secretName` set to `ingress.tlsSecretName` and `dnsNames` holding
`ingress.host`; cert-manager then renews it before it expires. Alternatively,
add your issuer annotation through `ingress.annotations`. Keeplane does not
install or require cert-manager, and this has not been tested with it.

**If it expires.** Browsers show a certificate warning and refuse to sign in;
the CLI refuses to connect with "Cannot reach Keeplane securely; check the
server and certificate configuration." Nothing inside Keeplane changes, and
model calls already under way are not affected. Replace the Secret as above;
no restart is needed.

**Developers with a private CA.** If the public certificate comes from your own
CA, developers' machines must trust it. The CLI uses the trust store of the
Python that runs it. Either add the CA to the operating system's trust store,
or point `SSL_CERT_FILE` at a PEM bundle that holds your CA (plus any public
CAs the machine needs) before running `keeplane`:

```sh
export SSL_CERT_FILE="$HOME/.config/keeplane/ca-bundle.pem"
keeplane whoami --profile "$HOME/.config/keeplane/account"
```

The CLI passes `SSL_CERT_FILE` and `SSL_CERT_DIR` on to the coding tool it
starts. Whether that tool honours them depends on the tool; check it with your
private CA before rolling out. When your CA itself is replaced, give developers
the new CA before the server switches to a certificate from it.

## Renew the PostgreSQL server certificate

Your database operator renews this certificate on the database server. Keeplane
needs only two things: its names must still include `app.postgres.host`, since
the app always uses `verify-full`; and it must be issued by a CA in the mounted
database CA file. If the issuing CA stays the same, nothing changes in
Kubernetes. Expected result after the server loads it: `check_credentials`
shows the new expiry date under `database_server`, `"trusted": true`.

If the new certificate comes from a different CA, follow
[rotate the database CA](postgres-accounts.md#rotate-the-database-ca) first, so
that the app trusts both CAs before the server switches.

**If it expires, or the server presents a certificate the app does not trust.**
Each app copy's new database connections fail verification; `/health/ready`
answers 503, the copies leave the Service and people see Keeplane as
unavailable. Copies stay alive (liveness does not depend on the database), so
they recover by themselves, without a restart, as soon as the server presents a
valid certificate. `check_credentials` then reports `"database": "unreachable"`
and, under `database_server`, the reason. The migration Job fails the same way,
which stops a Helm install or upgrade before it changes anything.

## Renew the database CA

`check_credentials` lists every CA in `app.postgres.caSecret` with its expiry
date. Renew it with the overlap steps in
[rotate the database CA](postgres-accounts.md#rotate-the-database-ca): put a
bundle of the old and new CA in the Secret, wait until every app pod reads it,
switch the server, then remove the old CA. No restart and no refused request.

An expired CA in the file fails `check_credentials` even when the server's
certificate comes from another CA in the bundle, so remove a CA you no longer
need. If the only CA that issued the server's certificate expires, the app
can no longer verify the server, with the effect described above.

## Customer-run gateway over HTTPS

In existing mode (`gateway.mode=existing`), `gateway.url` and each
`gateway.copyUrls` entry may use `https`. The app and preflight Job verify the
gateway's certificate and its name against the image's system CAs. If the
gateway's certificate comes from a private CA, put that CA in a Secret and name
it in `gateway.caSecret`; the chart mounts it into the app copies and preflight
Job at `/run/keeplane-gateway-ca/ca.crt`, in addition to the system CAs:

```sh
kubectl -n "$NS" create secret generic customer-gateway-ca --from-file=ca.crt=gateway-ca.crt
```

```yaml
gateway:
  mode: existing
  install: false
  url: https://gateway.example.internal
  caSecret: customer-gateway-ca
```

Helm refuses `gateway.caSecret` with the managed gateway. If the preflight Job
does not trust the gateway, it fails with "Gateway TLS certificate is not
trusted:" and the reason, and Helm stops before changing anything.

**Renew the gateway's certificate** in the gateway's own installation. If the
issuing CA stays the same, nothing changes in Keeplane. **Replace the CA**
with the same overlap as the database CA: write a bundle of the old and new CA
to `ca.crt` in the Secret, wait until every app pod reads it (`mounted_sha
<pod> /run/keeplane-gateway-ca/ca.crt`, from
[before and after every rotation](postgres-accounts.md#before-and-after-every-rotation)),
switch the gateway's certificate, then leave only the new CA. The app reads the
file again whenever it changes, so no restart is needed. `check_credentials`
shows `gateway_ca` and, for each copy, `gateway_servers` with `"trusted": true`.

**If it expires or is not trusted.** Calls from the app to the gateway fail:
model registration and changes report the gateway as unavailable, and the
check reports `"gateway"` keys as `unreachable`. Renew the certificate or fix
the CA Secret; the app recovers without a restart.

## What these checks prove

The [certificate operations cases](../../tests/unit/certificate-operations-cases.md)
list what is tested: expiry reporting with real certificates, the checks of a
PostgreSQL-style and an HTTPS server, a gateway CA renewed under a running app,
the CLI's `SSL_CERT_FILE`, and the chart's render checks. They do not prove a
renewal on a live cluster, an ingress controller's reload time, or cert-manager.
