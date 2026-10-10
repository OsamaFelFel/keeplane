#!/bin/sh
# Start the disposable Kubernetes integration trial. Every Kubernetes command
# uses this project's isolated kubeconfig, never the workstation default.
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
KUBECONFIG_PATH=${KEEPLANE_KUBECONFIG:-/private/tmp/keeplane-kind-kubeconfig}
HELM_BIN=${KEEPLANE_HELM_BIN:-helm}
PYTHON_IMAGE=python@sha256:2d9aefe2fef018a7eb2c13064c89c71929800fd2e5dccdbf52ea5da5bb8d929a
POSTGRES_IMAGE=postgres@sha256:721873c34ceb9f8d8fc265984940dc982404c105f19ad51be9fdc5970a6080ea
GATEWAY_IMAGE=cr.agentgateway.dev/agentgateway@sha256:9d3e6044ddcdc0878b1787f77bd401252b95e22684203fb5e874c4c42d2ed90c
QWEN_MODEL=models/qwen2.5-coder-0.5b-instruct-q4_k_m.gguf
QWEN_SHA256=1d9614638d18024d0fbb36575a15f1302a3adf044df10345688ec4f6e1c4ff32
RUNTIME_DIR=/private/tmp/keeplane-accounts-trial
FIRST_ADMIN_PASSWORD="$RUNTIME_DIR/first-admin-password"

cd "$ROOT"
if [ ! -f "$QWEN_MODEL" ]; then
  printf 'Missing %s; download it using docs/guide/local-preview.md first.\n' "$QWEN_MODEL" >&2
  exit 1
fi
ACTUAL_QWEN_SHA256=$(shasum -a 256 "$QWEN_MODEL" | cut -d ' ' -f 1)
if [ "$ACTUAL_QWEN_SHA256" != "$QWEN_SHA256" ]; then
  printf 'Qwen model checksum does not match the pinned file.\n' >&2
  exit 1
fi
mkdir -p "$RUNTIME_DIR"
chmod 700 "$RUNTIME_DIR"
if [ ! -f "$FIRST_ADMIN_PASSWORD" ]; then
  python3 -c 'import pathlib,secrets,sys; p=pathlib.Path(sys.argv[1]); p.write_text(secrets.token_urlsafe(32)+"\n"); p.chmod(0o600)' "$FIRST_ADMIN_PASSWORD"
fi
python3 - "$RUNTIME_DIR" <<'PY'
import hashlib
from pathlib import Path
import secrets
import sys

root = Path(sys.argv[1])
for kind in ("runtime", "admin"):
    path = root / f"gateway-{kind}-key"
    if not path.exists():
        path.write_text(secrets.token_urlsafe(32) + "\n")
        path.chmod(0o600)
    digest = hashlib.sha256(path.read_text().strip().encode()).hexdigest()
    hash_path = root / f"gateway-{kind}-key-hash"
    hash_path.write_text("sha256:" + digest + "\n")
    hash_path.chmod(0o600)
cloud_key = root / "cloud-provider-key"
if not cloud_key.exists():
    cloud_key.write_text(secrets.token_urlsafe(32) + "\n")
    cloud_key.chmod(0o600)
PY
if [ ! -d components/admin-ui/web/node_modules ]; then
  (cd components/admin-ui/web && npm ci)
fi
(cd components/admin-ui/web && npm run build)
docker pull "$PYTHON_IMAGE"
docker pull "$POSTGRES_IMAGE"
docker pull "$GATEWAY_IMAGE"
docker build -f components/control-plane/Dockerfile -t keeplane-preview:kind-local .

if kind get clusters | rg -xq keeplane; then
  kind export kubeconfig --name keeplane --kubeconfig "$KUBECONFIG_PATH"
else
  kind create cluster --name keeplane --image kindest/node:v1.37.0@sha256:a1ed56cfb0e7b93589bdf97c8cd566405a265939e3620fc4f5de89adff580ae5 \
    --config deploy/local/kind.yaml --kubeconfig "$KUBECONFIG_PATH" --wait 120s
fi
kind load docker-image "$PYTHON_IMAGE" "$POSTGRES_IMAGE" "$GATEWAY_IMAGE" \
  keeplane-preview:kind-local --name keeplane
docker exec keeplane-control-plane mkdir -p /models
docker cp "$QWEN_MODEL" "keeplane-control-plane:/models/$(basename "$QWEN_MODEL")"

kubectl --kubeconfig "$KUBECONFIG_PATH" create namespace keeplane --dry-run=client -o yaml |
  kubectl --kubeconfig "$KUBECONFIG_PATH" apply -f -
kubectl --kubeconfig "$KUBECONFIG_PATH" -n keeplane create secret generic keeplane-first-admin \
  --from-file=first-admin-password="$FIRST_ADMIN_PASSWORD" --dry-run=client -o yaml |
  kubectl --kubeconfig "$KUBECONFIG_PATH" -n keeplane apply -f -
kubectl --kubeconfig "$KUBECONFIG_PATH" create namespace keeplane-existing --dry-run=client -o yaml |
  kubectl --kubeconfig "$KUBECONFIG_PATH" apply -f -
kubectl --kubeconfig "$KUBECONFIG_PATH" -n keeplane-existing create secret generic keeplane-first-admin \
  --from-file=first-admin-password="$FIRST_ADMIN_PASSWORD" --dry-run=client -o yaml |
  kubectl --kubeconfig "$KUBECONFIG_PATH" -n keeplane-existing apply -f -
kubectl --kubeconfig "$KUBECONFIG_PATH" create namespace supplied-gateway --dry-run=client -o yaml |
  kubectl --kubeconfig "$KUBECONFIG_PATH" apply -f -
for NS in keeplane supplied-gateway keeplane-existing; do
  kubectl --kubeconfig "$KUBECONFIG_PATH" -n "$NS" create secret generic keeplane-gateway-keys \
    --from-file=runtime-key="$RUNTIME_DIR/gateway-runtime-key" \
    --from-file=admin-key="$RUNTIME_DIR/gateway-admin-key" \
    --from-file=runtime-key-hash="$RUNTIME_DIR/gateway-runtime-key-hash" \
    --from-file=admin-key-hash="$RUNTIME_DIR/gateway-admin-key-hash" \
    --dry-run=client -o yaml |
    kubectl --kubeconfig "$KUBECONFIG_PATH" -n "$NS" apply -f -
done
kubectl --kubeconfig "$KUBECONFIG_PATH" -n keeplane create configmap model-fixture \
  --from-file=mock_model.py=tests/fixtures/mock_model.py --dry-run=client -o yaml |
  kubectl --kubeconfig "$KUBECONFIG_PATH" -n keeplane apply -f -
kubectl --kubeconfig "$KUBECONFIG_PATH" -n keeplane create configmap cloud-provider-fixture \
  --from-file=cloud_provider.py=tests/fixtures/cloud_provider.py --dry-run=client -o yaml |
  kubectl --kubeconfig "$KUBECONFIG_PATH" -n keeplane apply -f -
kubectl --kubeconfig "$KUBECONFIG_PATH" -n keeplane create secret generic cloud-provider-key \
  --from-file=key="$RUNTIME_DIR/cloud-provider-key" --dry-run=client -o yaml |
  kubectl --kubeconfig "$KUBECONFIG_PATH" -n keeplane apply -f -
kubectl --kubeconfig "$KUBECONFIG_PATH" -n keeplane apply -f deploy/local/model-fixture.yaml
kubectl --kubeconfig "$KUBECONFIG_PATH" -n keeplane apply -f deploy/local/cloud-provider-fixture.yaml
kubectl --kubeconfig "$KUBECONFIG_PATH" -n keeplane apply -f deploy/local/qwen-runner.yaml
kubectl --kubeconfig "$KUBECONFIG_PATH" -n keeplane apply -f deploy/local/postgres-fixture.yaml
kubectl --kubeconfig "$KUBECONFIG_PATH" -n supplied-gateway create configmap model-fixture \
  --from-file=mock_model.py=tests/fixtures/mock_model.py --dry-run=client -o yaml |
  kubectl --kubeconfig "$KUBECONFIG_PATH" -n supplied-gateway apply -f -
kubectl --kubeconfig "$KUBECONFIG_PATH" -n supplied-gateway apply -f deploy/local/model-fixture.yaml
kubectl --kubeconfig "$KUBECONFIG_PATH" -n supplied-gateway apply -f deploy/local/postgres-fixture.yaml
kubectl --kubeconfig "$KUBECONFIG_PATH" -n keeplane rollout restart deployment/model
kubectl --kubeconfig "$KUBECONFIG_PATH" -n keeplane rollout restart deployment/cloud-provider
kubectl --kubeconfig "$KUBECONFIG_PATH" -n supplied-gateway rollout restart deployment/model
kubectl --kubeconfig "$KUBECONFIG_PATH" -n keeplane rollout status deployment/model --timeout=120s
kubectl --kubeconfig "$KUBECONFIG_PATH" -n keeplane rollout status deployment/cloud-provider --timeout=120s
kubectl --kubeconfig "$KUBECONFIG_PATH" -n keeplane rollout status deployment/qwen --timeout=300s
kubectl --kubeconfig "$KUBECONFIG_PATH" -n keeplane rollout status deployment/postgres --timeout=120s
kubectl --kubeconfig "$KUBECONFIG_PATH" -n supplied-gateway rollout status deployment/model --timeout=120s
kubectl --kubeconfig "$KUBECONFIG_PATH" -n supplied-gateway rollout status deployment/postgres --timeout=120s

"$HELM_BIN" upgrade --install keeplane deploy/helm/keeplane \
  --kubeconfig "$KUBECONFIG_PATH" --namespace keeplane \
  -f deploy/local/values.yaml --wait --timeout 180s
kubectl --kubeconfig "$KUBECONFIG_PATH" -n keeplane rollout restart deployment/keeplane-app
kubectl --kubeconfig "$KUBECONFIG_PATH" -n keeplane rollout status deployment/keeplane-app --timeout=120s

"$HELM_BIN" upgrade --install supplied-gateway \
  deploy/helm/keeplane/charts/agentgateway-standalone-v1.6.0.tgz \
  --kubeconfig "$KUBECONFIG_PATH" --namespace supplied-gateway \
  -f deploy/local/supplied-gateway-values.yaml --wait --timeout 180s

"$HELM_BIN" upgrade --install keeplane-existing deploy/helm/keeplane \
  --kubeconfig "$KUBECONFIG_PATH" --namespace keeplane-existing \
  -f deploy/local/existing-values.yaml \
  --wait --timeout 180s
kubectl --kubeconfig "$KUBECONFIG_PATH" -n keeplane-existing rollout restart deployment/keeplane-existing-app
kubectl --kubeconfig "$KUBECONFIG_PATH" -n keeplane-existing rollout status deployment/keeplane-existing-app --timeout=120s

printf 'Keeplane local Kubernetes trial: http://127.0.0.1:13000\n'
