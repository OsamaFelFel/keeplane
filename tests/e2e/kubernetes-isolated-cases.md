# Isolated-network Kubernetes cases

**Edition:** Open Source. Spec 002 ST1 and ST2 (task 002-03, and the enforced
ingress and egress policy of task 002-02), [ADR 009](https://github.com/OsamaFelFel/keeplane-governance/blob/main/adrs/0009-isolated-network.md).

The **Chart on an isolated kind network** job of the **Kubernetes live checks**
workflow (`.github/workflows/kubernetes-live.yml`) runs these cases on every
pull request and every push to main, with
[`test_kubernetes_isolated.py`](test_kubernetes_isolated.py) (ISO-01 to
ISO-12) and then
[`test_kubernetes_isolated_protected.py`](test_kubernetes_isolated_protected.py)
(ISO-13 to ISO-20, the protected developer release). The job fails if any case
is missing, skipped or failing.

## The network

- A disposable kind cluster, `keeplane-isolated`, on a Docker network with a
  fixed address range (172.30.0.0/16) and bridge name, so the closing rules and
  the model provider's address are known before the install
  ([cluster config](../fixtures/isolated-network/kind.yaml)).
- Calico replaces kind's own network plugin, so NetworkPolicy is enforced.
- ingress-nginx publishes Keeplane on `https://keeplane.isolated.test` with a
  certificate from a one-day CA the run makes. The runner reaches the ingress
  controller on its loopback address only.
- The model provider is
  [`cloud_provider.py`](../fixtures/cloud_provider.py) running on the runner,
  outside the cluster, at 172.30.0.1:18082, for the local-trial release. It
  checks the provider key and counts the calls it answers. A second copy
  serves the protected release over HTTPS at 172.30.0.1:443, with a
  certificate for `api.openai.com` from the run's CA; the cluster DNS answers
  that name with this address. The runner is the network's one outside place,
  and these two ports are all it answers there.
- Keeplane is installed in managed mode with two gateway copies and every
  opt-in NetworkPolicy on
  ([values](../fixtures/isolated-network/values.yaml)): the app admits only the
  ingress controller, the gateway copies admit only the app, and the app and
  gateway copies may reach only DNS, the gateway database and the two model
  endpoints (the provider outside and the fixture model inside).
- An internal registry, `keeplane-mirror`, runs on the same Docker network at
  172.30.0.200:5000 ([config](../fixtures/isolated-network/registry.yml)).
  Before the cluster exists, while the outside registries are reachable, the
  job copies into it every image the install's manifests name (Calico,
  ingress-nginx, the rendered chart, the gateway database and model
  fixtures and the `inside` pods) and the Python image the cases join to a
  gateway copy, each by its digest
  ([script](../fixtures/isolated-network/mirror.py)). It pushes the app image
  there too, and the chart names it as
  `172.30.0.200:5000/keeplane/app@sha256:<digest>`. An image from registry R
  is kept under R's name (for example `quay.io/calico/node`); for an image
  index only the linux/amd64 image is copied and the index keeps its digest.
  The node's containerd is then told to try the internal registry first for
  every one of those registries, so the install already pulls from it. The
  images Kubernetes itself runs (the API server, CoreDNS, kube-proxy, the
  pause image) come inside the kind node image and are not pulled.
- The protected developer release runs beside it in namespace
  `keeplane-protected` ([setup](../fixtures/isolated-network/protected.py),
  [values](../fixtures/isolated-network/protected-values.yaml)): the
  PostgreSQL install with CLI sign-in, two app replicas, the managed gateway
  with the model enroller on both copies, and one public address,
  `https://keeplane-protected.isolated.test`, through the same ingress
  controller, for the web UI, the CLI and protected model calls. It uses the
  chart values of the kind job's protected release
  ([`protected-values.yaml`](../../deploy/local/protected-values.yaml),
  [developer cases](kubernetes-developer-cases.md)), the same disposable
  account database with TLS and gateway database, and every opt-in
  NetworkPolicy: the app and gateway copies may reach only DNS, the account
  database, the gateway database (the copies only), each other and the
  provider at 172.30.0.1:443, and only the ingress controller reaches the app
  and the protected model port. Its app image is built from the same revision
  (`postgres-cli-auth-trial`), pushed to the internal registry and named
  there by digest. It is installed after the local-trial release, while the
  registry is still reachable.
- Namespace `inside` holds two pods of a team's own with no policy
  ([fixture](../fixtures/isolated-network/inside.yaml)): `service`, an HTTP
  service not on Keeplane's egress list, and `visitor`, which makes calls from
  inside the network.
- Closing the network ([script](../fixtures/isolated-network/close-network.sh))
  adds runner firewall rules: nothing from the network is forwarded anywhere,
  and the runner answers the network only on the model provider's port and on
  connections the runner opened itself. Traffic inside the network, such as
  the node's pulls from the internal registry, stays on the bridge and keeps
  working. It also closes outside name lookups.
  The node's resolver is Docker's embedded DNS, which looks names up from the
  runner and so is not stopped by those rules; inside the node every packet to
  it is refused, and a unit in the node adds the same rules on every boot, so
  they hold across the node restart. CoreDNS gets a
  [closed configuration](../fixtures/isolated-network/Corefile) with no
  forward: it still answers names inside the cluster and answers "no such
  name" for every other name, as a DNS server with no upstream does, except
  `api.openai.com`, which it answers with the runner's address, as an isolated
  network's own DNS answers for the one provider it allows. It is then
  restarted, so it holds no name it looked up before closing.

## Components added for this run

| Component | Version | Pinned by | Licence | Role |
| --- | --- | --- | --- | --- |
| Calico | v3.33.0 | Manifest SHA-256 and the digest of each of its three images | Apache-2.0 | Enforcing network plugin, test only |
| ingress-nginx | controller-v1.15.1 | Manifest SHA-256; the manifest names every image by digest | Apache-2.0 | Ingress controller fixture, test only; not a release choice |
| Distribution registry (`registry` image) | 3.1.1 | Image digest | Apache-2.0 | The internal registry, test only; not a release choice |
| crane (go-containerregistry) | v0.22.1 | Release archive SHA-256 from its `checksums.txt` | Apache-2.0 | Copies images into the internal registry, on the runner only |

kind, kubectl and Helm use the same pinned versions and checksums as the
Kubernetes live checks. None of these components ships with Keeplane.

## Cases

A connection counts as blocked only when it times out, is reset or refused, or
is answered "host unreachable", the ways a policy or the closed firewall stops
it. Outside places are probed by IP address, so a failed name lookup never
counts as a block. A name lookup counts as closed only when it fails; the
lookups before closing show the same name resolved.

| ID | Plain-English action | Expected result |
| --- | --- | --- |
| ISO-01 | Before closing the network, check the node can reach the container registry, every Keeplane pod is ready, and read every image the Keeplane pods run. Then, while the runner still forwards everything, connect to an internet address (1.1.1.1:443) and the registry, both by IP address, from the `visitor` pod and the fixture model's pod (no policy on either), from the app pod and from gateway copy 0. Look up `registry.k8s.io` from the node and the `visitor` pod. | The node reaches the registry (the install pulled the gateway, PostgreSQL and fixture images by digest during the install). Every image is pinned by digest, the app image too, which is named in the internal registry. Both pods with no policy reach the internet address and the registry, while the app and the gateway copy can't: their egress policy alone stops them. The name resolves from the node and the visitor. |
| ISO-02 | Before closing, check the node lacks an image, pull it from the registry and remove it again. Close the network. Look up `registry.k8s.io` from the node, the app pod and the `visitor` pod, and an in-cluster name from the app and the visitor. From the node, contact the registry and pull the same image again; from the `visitor` pod, connect to the internet address, the registry by IP address and the model provider. | The image pulls before closing, so the reference is good. Both pulls go straight to the outside registry, not through the internal one, which does not hold this image. After closing, and within 90 seconds (a CoreDNS copy that is still stopping may answer from its 30-second cache), `registry.k8s.io` resolves from none of the three, while the in-cluster names still resolve. The registry can't be reached and the pull fails, without the registry rejecting the reference. The visitor can't reach the internet or the registry, and still reaches the model provider. |
| ISO-03 | Delete every pod in the Keeplane namespace (app, both gateway copies, gateway database, fixture model) and the ingress controller pod, and wait for them to come back. | All come back ready as new pods, with no image pull attempted: every image was already on the node. |
| ISO-04 | Open the web UI at `https://keeplane.isolated.test` from the runner, trusting only the run's CA, and from the `visitor` pod through the ingress controller's Service. | The page, health check and a bundled font load from the runner with the certificate verified, and the visitor gets the page too. |
| ISO-05 | Sign in as the first admin, add a cloud model on the model provider outside the cluster with a shared provider key, and ask it a question. | The model is added and listed as a cloud model, the answer comes back, and the provider counts the call. |
| ISO-06 | Set up the fixture model inside the cluster and ask it a question, reading the outside model provider's call count before and after. | The answer comes back through the managed gateway, and the outside provider's call count stays the same. |
| ISO-07 | From the app pod and from gateway copy 0 (through a pinned Python container joined to its Pod, since the gateway image has no shell), contact the model provider, the `service` pod in `inside`, the internet address and the registry by IP address. From the fixture model's pod, which has no policy, contact `service`. | The app and the gateway copy reach the model provider and nothing else: `service` is blocked by the egress policy even though the unrestricted pod reaches it, and the internet and registry are blocked (ISO-01 showed the policy blocks them before the network closed). |
| ISO-08 | From the `visitor` pod and from the fixture model's pod in Keeplane's own namespace, call the app on port 3000 and the gateway on port 4000 directly, and call the fixture model. | Both direct calls are blocked from both pods, while the fixture model answers the visitor: only the ingress controller reaches the app, and only the app reaches the gateway. |
| ISO-09 | Restart the cluster's node with the network still closed, wait for it and for every pod (the protected release's too) to run containers started after the restart and be ready, then open the web UI, sign in again and ask both models. Look up `registry.k8s.io` from the node and the app pod, and an in-cluster name from the app. | The node starts from the images it holds, the page opens, both models answer, the node and app still can't reach the registry or the internet, the outside name still resolves from neither, and the in-cluster name resolves. |
| ISO-10 | With the network still closed, list every image any pod in the cluster names (ephemeral probe containers included) that the kind node image did not already hold, and compare it with what the internal registry holds. From the node, ask the internal registry for each image it holds by digest, and for an index its linux/amd64 image too. | Every image the cluster runs is in the internal registry, pinned by digest, and the registry serves each of them to the node with the same digest while the node still can't reach the outside registry. |
| ISO-11 | Make the node fresh: stop its kubelet and remove every image the kind node image did not hold, so only Kubernetes' own images stay. Then start the node with the network still closed and wait for it, Calico, CoreDNS, every Keeplane pod of both releases, the ingress controller and the `inside` pods to be ready. Read the internal registry's access log since the restart. | Before the restart none of the removed images is left on the node. Afterwards every pod is ready, every image the pods run is on the node again, and the access log shows the node fetched each of them by digest from the internal registry. The node still can't reach the outside registry. |
| ISO-12 | On that fresh node, open the web UI, sign in again and ask both models. From the app pod and from gateway copy 0 (its probe container pulled from the internal registry), contact the model provider, the internet address and the registry by IP address. Look up `registry.k8s.io` from the node and the app pod, and an in-cluster name from the app. | The page opens, both models answer, the app and the gateway copy reach the model provider and nothing else outside, `registry.k8s.io` still resolves from neither, and the in-cluster name resolves. |

### The protected developer release (ISO-13 to ISO-20)

These run after ISO-12, on the fresh node with the network still closed. The
runner plays a developer's computer outside the cluster: it reaches Keeplane
only through the public address, and runs the CLI from the source tree with
the run's CA as its only extra trust. The fixture browser is a script that
opens Keeplane's real sign-in and consent pages, as a person would in a
browser. A gateway copy's probe also stands for its model enroller, which
shares the copy's Pod and so its network and policy.

| ID | Plain-English action | Expected result |
| --- | --- | --- |
| ISO-13 | Check the network is still closed: the node contacts the outside registry and the `visitor` pod connects to the internet address. Wait for the protected release's pods, read every image they run and compare it with what the internal registry holds, and ask its public address for `/health/ready`. | The registry and the internet can't be reached. Every pod is ready (two app replicas and both gateway copies among them), every image is pinned by digest and held by the internal registry, the app image is the one pushed there, and the public address answers ready with its certificate verified. |
| ISO-14 | Sign in to `https://keeplane-protected.isolated.test` as the first admin (PostgreSQL accounts), create a developer, and add a cloud model on the provider outside the cluster (`api.openai.com`) with a shared key, approved for Public. Read the provider's count for that key before and after, and each gateway copy's model enroller report. | The model is added, approved and listed as a cloud model; adding it sent the shared key to the provider at least once, so the gateway reached the provider by its name over TLS. Both copies' enrollers report the model enrolled for protected access. |
| ISO-15 | On the runner, the developer runs `keeplane login --server https://keeplane-protected.isolated.test` into one profile, which opens the fixture browser: it signs in and allows CLI access. Then `keeplane whoami`. | Sign-in exits 0 with `Signed in to Keeplane.` and `whoami` names the developer. The saved sign-in is for the public address, with the gateway address the server gave: `https://keeplane-protected.isolated.test/v1`. |
| ISO-16 | Into a second profile, the developer runs `keeplane login --device` and approves the code from another device (a separate browser session on the device pages), then `keeplane whoami`. | The code is shown for the public address's device page, approval succeeds, sign-in exits 0 with `Signed in to Keeplane.`, `whoami` names the developer and the saved gateway is the public `/v1` address. |
| ISO-17 | The developer registers a project with `keeplane register-project` and runs `keeplane models`. With each profile's sign-in, and once with none, they send a request for the model straight to `https://keeplane-protected.isolated.test/v1/chat/completions`. | Both commands exit 0 and the model is listed. Both signed-in requests answer 200 with "mock cloud answer", and the provider outside answered the shared key at least once for each. The request without a sign-in is refused with 401 or 403 and no answer, and reaches no provider. |
| ISO-18 | From the protected app pod and from its gateway copy 0 (a pinned Python container joined to its Pod, which also holds the model enroller), connect to the provider (172.30.0.1:443), the account database, the gateway database, each other, the local-trial release's provider port (172.30.0.1:18082) and its fixture model, the `service` pod in `inside`, the internet address and the registry by IP address. From the app, look up `api.openai.com`, `registry.k8s.io` and the account database's name. | The app reaches the provider, the account database and its gateway, and nothing else: the gateway database is blocked for it. The gateway copy reaches the provider, both databases and the app (the enroller's and the protected runtime's paths). Neither reaches the other release's provider port or model, `service`, the internet or the registry. `api.openai.com` resolves to 172.30.0.1, `registry.k8s.io` doesn't resolve and the database name does. |
| ISO-19 | From the `visitor` pod and from the local-trial release's fixture model pod, call the protected app on port 3000, its gateway on 4000 and the protected model port 5000 directly, and call the fixture model. | All three direct calls are blocked from both pods, while the fixture model answers the visitor: only the ingress controller reaches the app and the protected model port, and only the app reaches the gateway's port 4000. |
| ISO-20 | Restart the node with the network still closed. Wait for every pod of the protected release to run containers started after the restart and be ready, and for both enrollers to report the model again. Then ask the public address for `/health/ready`, run `keeplane whoami` with the browser sign-in, sign in with the device code into a new profile, send the signed-in and unsigned requests again, and repeat ISO-18's checks. | The node still can't reach the registry. Every pod comes back ready, the enrollers report the model enrolled, the public address answers ready, the browser sign-in from before the restart still works, the new device sign-in succeeds, both signed-in requests get the answer from the provider outside while the unsigned one is refused, and the app and gateway copy still reach only their declared places. |

Afterwards the CLI signs out of every profile; the cluster is disposable.

## Not covered here

- A customer-run gateway, the coding runtime (`keeplane code`), developers'
  own provider keys, personal-data detection, held records, audit and the
  other admin screens, and external identity providers on the isolated
  network. The kind job's [developer cases](kubernetes-developer-cases.md)
  run `keeplane code` and own keys on the protected release, on a cluster
  with outside access.
- A real browser for the CLI's sign-in: the fixture browser drives
  Keeplane's real pages over HTTP, as the other CLI sign-in suites do.
- A provider reached through a proxy, or with more than one address. The
  provider's name resolves to one address the policies list by `cidr`.
- A new node joining the cluster on the closed network. The fresh node here
  is the same node with every installed image removed (ISO-11); its kind node
  image still holds Kubernetes' own images, and Calico's network plugin
  files it installed earlier stay on its disk.
- A production registry for the mirror (authentication, TLS, a pull secret,
  storage and garbage collection), and images for other platforms than
  linux/amd64.
- A multi-node cluster and a production ingress controller and network plugin.
