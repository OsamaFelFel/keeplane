# Isolated-network Kubernetes cases

**Edition:** Open Source. Spec 002 ST1 and ST2 (task 002-03, and the enforced
ingress and egress policy of task 002-02), [ADR 009](https://github.com/OsamaFelFel/keeplane-governance/blob/main/adrs/0009-isolated-network.md).

The **Kubernetes isolated network** workflow
(`.github/workflows/kubernetes-isolated.yml`) runs these cases on every pull
request and every push to main, with
[`test_kubernetes_isolated.py`](test_kubernetes_isolated.py). The job fails if
any case is missing, skipped or failing.

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
  outside the cluster, at 172.30.0.1:18082: the network's one outside place.
  It checks the provider key and counts the calls it answers.
- Keeplane is installed in managed mode with two gateway copies and every
  opt-in NetworkPolicy on
  ([values](../fixtures/isolated-network/values.yaml)): the app admits only the
  ingress controller, the gateway copies admit only the app, and the app and
  gateway copies may reach only DNS, the gateway database and the two model
  endpoints (the provider outside and the fixture model inside).
- Namespace `inside` holds two pods of a team's own with no policy
  ([fixture](../fixtures/isolated-network/inside.yaml)): `service`, an HTTP
  service not on Keeplane's egress list, and `visitor`, which makes calls from
  inside the network.
- Closing the network ([script](../fixtures/isolated-network/close-network.sh))
  adds runner firewall rules: nothing from the network is forwarded anywhere,
  and the runner answers the network only on the model provider's port and on
  connections the runner opened itself.

## Components added for this run

| Component | Version | Pinned by | Licence | Role |
| --- | --- | --- | --- | --- |
| Calico | v3.33.0 | Manifest SHA-256 and the digest of each of its three images | Apache-2.0 | Enforcing network plugin, test only |
| ingress-nginx | controller-v1.15.1 | Manifest SHA-256; the manifest names every image by digest | Apache-2.0 | Ingress controller fixture, test only; not a release choice |

kind, kubectl and Helm use the same pinned versions and checksums as the
Kubernetes live checks. Neither component ships with Keeplane.

## Cases

| ID | Plain-English action | Expected result |
| --- | --- | --- |
| ISO-01 | Before closing the network, check the node can reach the container registry, every Keeplane pod is ready, and read every image the Keeplane pods run. | The node reaches the registry (the install pulled the gateway, PostgreSQL and fixture images by digest during the install). Every image is pinned by digest, except the app image, which was loaded into the node and is never pulled. A pod with no policy can still reach an internet address. |
| ISO-02 | Close the network. From the node, contact the registry and pull an image it never had; from the `visitor` pod, connect to an internet address, the registry and the model provider. | The registry can't be reached and the pull fails. The visitor can't reach the internet or the registry, and still reaches the model provider. |
| ISO-03 | Delete every pod in the Keeplane namespace (app, both gateway copies, gateway database, fixture model) and the ingress controller pod, and wait for them to come back. | All come back ready as new pods, with no image pull attempted: every image was already on the node. |
| ISO-04 | Open the web UI at `https://keeplane.isolated.test` from the runner, trusting only the run's CA, and from the `visitor` pod through the ingress controller's Service. | The page, health check and a bundled font load from the runner with the certificate verified, and the visitor gets the page too. |
| ISO-05 | Sign in as the first admin, add a cloud model on the model provider outside the cluster with a shared provider key, and ask it a question. | The model is added and listed as a cloud model, the answer comes back, and the provider counts the call. |
| ISO-06 | Set up the fixture model inside the cluster and ask it a question. | The answer comes back through the managed gateway. |
| ISO-07 | From the app pod and from gateway copy 0 (through a pinned Python container joined to its Pod, since the gateway image has no shell), contact the model provider, the `service` pod in `inside`, an internet address and the registry. From the fixture model's pod, which has no policy, contact `service`. | The app and the gateway copy reach the model provider and nothing else: `service` is blocked by the egress policy even though the unrestricted pod reaches it, and the internet and registry are blocked. |
| ISO-08 | From the `visitor` pod and from the fixture model's pod in Keeplane's own namespace, call the app on port 3000 and the gateway on port 4000 directly, and call the fixture model. | Both direct calls are blocked from both pods, while the fixture model answers the visitor: only the ingress controller reaches the app, and only the app reaches the gateway. |
| ISO-09 | Restart the cluster's node with the network still closed, wait for it and every pod to be ready, then open the web UI, sign in again and ask both models. | The node starts from the images it holds, the page opens, both models answer, and the node and app still can't reach the registry or the internet. |

## Not covered here

- The developers' protected model path (`/v1/chat/completions` on the public
  host, through the model enroller). It needs the PostgreSQL install with TLS
  and the enroller's database roles; no kind install of it exists yet.
- The PostgreSQL install of the app, a customer-run gateway, browser and device
  sign-in, the coding runtime on developer machines and external identity
  providers on the isolated network.
- A multi-node cluster, a production ingress controller and network plugin, and
  an internal registry mirror. The install here pulls from the public
  registries while they are reachable; an isolated site would pull from its own
  mirror the same way.
