#!/usr/bin/env bash
# provision-kwok-layer.sh — Deploy the KWOK + mock-cilium-agent layer onto ONE
# Fleet-meshed AKS cluster, at N virtual nodes.
#
# This is the per-cluster "mock layer" that sits on top of a base cluster created
# by fleet-setup-script.sh. It:
#   1. Installs the KWOK controller (pinned to the real node pool) + lifecycle Stages.
#   2. Creates N KWOK virtual nodes, each with a DISTINCT podCIDR (10.245.<i>.0/24)
#      so KWOK assigns globally-unique Pod IPs within the cluster.
#   3. Deploys N mock-cilium-agents (one per virtual node, on the real pool),
#      each with K8S_NODE_NAME=<node> and Prometheus metrics enabled.
#
# Design notes baked in (from prior findings):
#   - KWOK gives each Pod a unique IP from node.spec.podCIDR on the real
#     Pod.status.podIP — so Pod == EndpointSlice == CiliumEndpoint (one IP, like CNI).
#   - Per-node podCIDR (10.245.<i>.0/24) keeps Pod IPs unique cluster-wide. 10.245/16
#     does not overlap the real node/pod subnets (10.<clusterid>.0/24 + .1.0/24).
#   - Agents run hostNetwork=false (own Pod IP), so metrics on :9962 do NOT collide
#     with the real AKS cilium-agent (hostNetwork, node-IP:9962) or with each other.
#   - cluster-name / cluster-id come from Fleet (read from managed cilium-config),
#     NOT hardcoded.
#
# Usage:
#   KUBECONFIG_FILE=~/.kube/mockmesh3-1 NODE_COUNT=3 \
#     ACR_HOST=mockmeshshared.azurecr.io AGENT_TAG=v26 \
#     ./provision-kwok-layer.sh
#
# Required:
#   KUBECONFIG_FILE   path to the target cluster's kubeconfig
#   ACR_HOST          ACR login server hosting mock-cilium-agent:<AGENT_TAG>
# Optional:
#   NODE_COUNT        virtual nodes to create (default 3)
#   AGENT_TAG         image tag (default v26)
#   AGENT_NS          namespace for agents (default mock-clustermesh)
#   AGENT_SA          service account (default mock-cilium-agent)
#   KWOK_VER          KWOK release (default v0.7.0)
#   METRICS_PORT      agent prometheus port (default 9962)
#   CONSUME_CLUSTERMESH  wire the clustermesh consume path (default true). When
#                     true, copies the local clustermesh client secrets into
#                     AGENT_NS and mounts them so each mock agent opens etcd
#                     watches against the local clustermesh-apiserver (consuming
#                     remote identities/endpoints/nodes/services). Set false for
#                     a publish-only layer.
set -euo pipefail

KUBECONFIG_FILE="${KUBECONFIG_FILE:?KUBECONFIG_FILE required}"
ACR_HOST="${ACR_HOST:?ACR_HOST required}"
NODE_COUNT="${NODE_COUNT:-3}"
AGENT_TAG="${AGENT_TAG:-v26}"
AGENT_NS="${AGENT_NS:-mock-clustermesh}"
AGENT_SA="${AGENT_SA:-mock-cilium-agent}"
KWOK_VER="${KWOK_VER:-v0.7.0}"
METRICS_PORT="${METRICS_PORT:-9962}"
CONSUME_CLUSTERMESH="${CONSUME_CLUSTERMESH:-true}"

K() { kubectl --kubeconfig="$KUBECONFIG_FILE" "$@"; }

echo "=============================================="
echo "  KWOK + mock-agent layer"
echo "  kubeconfig : ${KUBECONFIG_FILE}"
echo "  nodes      : ${NODE_COUNT}"
echo "  image      : ${ACR_HOST}/mock-cilium-agent:${AGENT_TAG}"
echo "  agent ns   : ${AGENT_NS}"
echo "=============================================="

# ---------------------------------------------------------------------------
# Cluster identity. Multi-cluster mesh tiers read the Fleet-assigned identity
# from cilium-config (do NOT hardcode). The single-cluster / no-Fleet baseline
# has no Fleet identity (cluster-id stays 0), so it passes MOCK_CLUSTER_ID /
# MOCK_CLUSTER_NAME explicitly. The ${VAR:-...} fallback runs the cilium-config
# read ONLY when the override is unset, so mesh-tier behavior is unchanged.
# ---------------------------------------------------------------------------
CLUSTER_NAME="${MOCK_CLUSTER_NAME:-$(K -n kube-system get cm cilium-config -o jsonpath='{.data.cluster-name}')}"
CLUSTER_ID="${MOCK_CLUSTER_ID:-$(K -n kube-system get cm cilium-config -o jsonpath='{.data.cluster-id}')}"
if [[ -z "${CLUSTER_NAME}" || -z "${CLUSTER_ID}" || "${CLUSTER_ID}" == "0" ]]; then
  echo "ERROR: no cluster identity (cluster-name='${CLUSTER_NAME}' cluster-id='${CLUSTER_ID}')." >&2
  echo "       Fleet-mesh the cluster first, or pass MOCK_CLUSTER_ID / MOCK_CLUSTER_NAME (no-Fleet baseline)." >&2
  exit 1
fi
echo ">>> Cluster identity: cluster-name=${CLUSTER_NAME} cluster-id=${CLUSTER_ID}"

# ---------------------------------------------------------------------------
# Inherit the CONTROL-PLANE-relevant subset of the managed (Fleet/AKS) cilium
# config, so the mock agent behaves like the managed cilium-agent would. The
# deploy layer is intentionally AKS-specific (it reads the managed cilium-config),
# while the FORK stays platform-agnostic — we just pass these as explicit flags.
#
# We deliberately DO NOT inherit datapath keys (routing-mode, enable-endpoint-
# routes, kube-proxy-replacement, bpf-*, ipam=delegated-plugin, masquerade,
# cni-*, ...): those are faked by the DryMode datapath and would break startup.
# We also skip operator/apiserver-only keys that are NOT cilium-agent flags
# (clustermesh-enable-endpoint-sync, clustermesh-enable-mcs-api,
# clustermesh-default-global-namespace).
#
# Of the keys below, only policy-default-local-cluster differs from the agent's
# compiled default (false->true); the rest match defaults and are set explicitly
# for robustness against future default drift + as self-documentation.
# ---------------------------------------------------------------------------
cfg() { K -n kube-system get cm cilium-config -o jsonpath="{.data.$1}" 2>/dev/null; }
IDENTITY_MGMT_MODE="$(cfg identity-management-mode)";               IDENTITY_MGMT_MODE="${IDENTITY_MGMT_MODE:-agent}"
MAX_CONNECTED_CLUSTERS="$(cfg max-connected-clusters)";             MAX_CONNECTED_CLUSTERS="${MAX_CONNECTED_CLUSTERS:-255}"
POLICY_DEFAULT_LOCAL_CLUSTER="$(cfg policy-default-local-cluster)"; POLICY_DEFAULT_LOCAL_CLUSTER="${POLICY_DEFAULT_LOCAL_CLUSTER:-true}"
ENABLE_K8S_NETWORKPOLICY="$(cfg enable-k8s-networkpolicy)";         ENABLE_K8S_NETWORKPOLICY="${ENABLE_K8S_NETWORKPOLICY:-true}"
CILIUMNODE_UPDATE_RATE="$(cfg ipam-cilium-node-update-rate)";       CILIUMNODE_UPDATE_RATE="${CILIUMNODE_UPDATE_RATE:-15s}"
echo ">>> Inherited control-plane config:"
echo "      identity-management-mode=${IDENTITY_MGMT_MODE} max-connected-clusters=${MAX_CONNECTED_CLUSTERS}"
echo "      policy-default-local-cluster=${POLICY_DEFAULT_LOCAL_CLUSTER} enable-k8s-networkpolicy=${ENABLE_K8S_NETWORKPOLICY}"
echo "      ipam-cilium-node-update-rate=${CILIUMNODE_UPDATE_RATE}"

# ---------------------------------------------------------------------------
# STEP 1: KWOK controller (pinned to real nodes) + lifecycle Stages
# ---------------------------------------------------------------------------
echo ">>> Step 1: Installing KWOK ${KWOK_VER}..."
WORK="$(mktemp -d)"
curl -sL -o "${WORK}/kwok.yaml"       "https://github.com/kubernetes-sigs/kwok/releases/download/${KWOK_VER}/kwok.yaml"
curl -sL -o "${WORK}/stage-fast.yaml" "https://github.com/kubernetes-sigs/kwok/releases/download/${KWOK_VER}/stage-fast.yaml"

python3 - "${WORK}/kwok.yaml" "${WORK}/kwok-patched.yaml" <<'PY'
import sys, yaml
src, dst = sys.argv[1], sys.argv[2]
docs = list(yaml.safe_load_all(open(src)))
for d in docs:
    if d and d.get('kind') == 'Deployment' and d['metadata']['name'] == 'kwok-controller':
        d['spec']['template']['spec']['affinity'] = {'nodeAffinity': {
            'requiredDuringSchedulingIgnoredDuringExecution': {'nodeSelectorTerms': [
                {'matchExpressions': [{'key': 'kubernetes.azure.com/cluster', 'operator': 'Exists'}]}]}}}
yaml.safe_dump_all(docs, open(dst, 'w'), default_flow_style=False)
PY
K apply -f "${WORK}/kwok-patched.yaml" >/dev/null
K apply -f "${WORK}/stage-fast.yaml" >/dev/null
K -n kube-system rollout status deploy/kwok-controller --timeout=120s

# ---------------------------------------------------------------------------
# STEP 2: RBAC for the agents (ServiceAccount + cluster-admin; tighten later)
# ---------------------------------------------------------------------------
echo ">>> Step 2: RBAC (${AGENT_NS}/${AGENT_SA})..."
K apply -f - >/dev/null <<EOF
apiVersion: v1
kind: Namespace
metadata: { name: ${AGENT_NS} }
---
apiVersion: v1
kind: ServiceAccount
metadata: { name: ${AGENT_SA}, namespace: ${AGENT_NS} }
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata: { name: ${AGENT_SA}-cluster-admin }
roleRef: { apiGroup: rbac.authorization.k8s.io, kind: ClusterRole, name: cluster-admin }
subjects: [{ kind: ServiceAccount, name: ${AGENT_SA}, namespace: ${AGENT_NS} }]
EOF

# ---------------------------------------------------------------------------
# STEP 2.5: ClusterMesh CONSUME path (optional, default on).
# Copy the local clustermesh client secrets from kube-system into AGENT_NS so the
# mock agents can mount them and open etcd watches against the LOCAL clustermesh-
# apiserver (kvstoremesh) — consuming remote identities/endpoints/nodes/services.
# This exercises the consumer-side serving fan-out on clustermesh-apiserver, which
# scales with (agents x mesh state) and is otherwise frozen at ~1 real agent.
#
# Why this is needed: Fleet only patches the MANAGED cilium DaemonSet to mount
# clustermesh-secrets; our mock agents are bare Pods it never reconciles, so we
# plumb the same secrets ourselves. The mesh-22-style config file points at the
# LOCAL service (clustermesh-apiserver.kube-system.svc:2379), so no cross-cluster
# networking is involved. The FORK stays agnostic — this is deploy-layer only.
# ---------------------------------------------------------------------------
CM_ARG=""; CM_MOUNT=""; CM_VOLUME=""
if [[ "${CONSUME_CLUSTERMESH}" == "true" ]] && K -n kube-system get secret cilium-clustermesh >/dev/null 2>&1; then
  echo ">>> Step 2.5: Wiring clustermesh CONSUME path (copying secrets -> ${AGENT_NS})..."
  STRIP='del(.metadata.namespace,.metadata.resourceVersion,.metadata.uid,.metadata.creationTimestamp,.metadata.ownerReferences,.metadata.managedFields,.metadata.annotations,.status)'
  for s in cilium-clustermesh clustermesh-apiserver-remote-cert clustermesh-apiserver-local-cert cilium-root-ca.crt; do
    if K -n kube-system get secret "$s" -o json 2>/dev/null | jq "${STRIP}" | K -n "${AGENT_NS}" apply -f - >/dev/null 2>&1; then
      echo "      copied secret ${s}"
    else
      echo "      WARN: secret ${s} not found in kube-system (skipping)"
    fi
  done
  CM_ARG="    - --clustermesh-config=/var/lib/cilium/clustermesh"
  CM_MOUNT="    - { name: clustermesh-secrets, mountPath: /var/lib/cilium/clustermesh, readOnly: true }"
  CM_VOLUME=$(cat <<'YAML'
  - name: clustermesh-secrets
    projected:
      defaultMode: 256
      sources:
      - secret: { name: cilium-clustermesh, optional: true }
      - secret: { name: clustermesh-apiserver-remote-cert, optional: true, items: [ { key: tls.key, path: common-etcd-client.key }, { key: tls.crt, path: common-etcd-client.crt } ] }
      - secret: { name: cilium-root-ca.crt, optional: true, items: [ { key: ca.crt, path: common-etcd-client-ca.crt } ] }
      - secret: { name: clustermesh-apiserver-local-cert, optional: true, items: [ { key: tls.key, path: local-etcd-client.key }, { key: tls.crt, path: local-etcd-client.crt } ] }
      - secret: { name: cilium-root-ca.crt, optional: true, items: [ { key: ca.crt, path: local-etcd-client-ca.crt } ] }
YAML
)
else
  echo ">>> Step 2.5: ClusterMesh CONSUME path DISABLED (publish-only). Set CONSUME_CLUSTERMESH=true to enable."
fi

# ---------------------------------------------------------------------------
# STEP 3: N virtual nodes (distinct podCIDR) + N mock-agents (with metrics)
# ---------------------------------------------------------------------------
echo ">>> Step 3: Generating ${NODE_COUNT} virtual node(s) + agent(s)..."
# Stream all manifests into two files and bulk-apply once per file (below).
# At NODE_COUNT=10000 the old per-node `kubectl apply -f -` (2 calls/node = 20k
# serial round-trips + process spawns) takes hours; bulk apply is minutes. For
# small N (multi-cluster tiers) this is identical output, just faster.
NODES_FILE="${WORK}/kwok-nodes.yaml"
AGENTS_FILE="${WORK}/mock-agents.yaml"
: > "$NODES_FILE"
: > "$AGENTS_FILE"
if [ "${NODE_COUNT}" -gt 32768 ]; then
  echo "ERROR: NODE_COUNT=${NODE_COUNT} exceeds 32768 (the >250 nodeIP scheme 100.128+.x tops out there)." >&2
  exit 1
fi
for i in $(seq 0 $((NODE_COUNT - 1))); do
  NODE="kwok-node-${i}"
  # Globally-unique podCIDR + nodeIP per node in the synthetic 100.0.0.0/8 space
  # (never routed; phantom-pod identifiers) so they never overlap the real VNet
  # (10.0.0.0/8). The node index needs TWO octets once NODE_COUNT>256:
  #   * NODE_COUNT<=250 (multi-cluster tiers): keep 100.<cluster_id>.<i>.0/24 —
  #     cluster-id in octet 2 makes Pod IPs unique ACROSS the mesh so remote
  #     backends don't collide; nodeIP 100.<cid>.255.<i> (the .255 octet avoids
  #     the podCIDRs at 0..NODE_COUNT).
  #   * NODE_COUNT>250 (single-cluster baseline only): use a 2-octet index
  #     100.<i/256>.<i%256>.0/24 (supports up to 32768 nodes — bounded by the
  #     nodeIP octet 100.128+.x below). This DROPS the cluster-id, so it is
  #     single-cluster-only — do NOT set NODE_COUNT>250 with more than one
  #     cluster. nodeIP goes in a disjoint 100.128+.x block.
  if [ "${NODE_COUNT}" -le 250 ]; then
    PODCIDR="100.${CLUSTER_ID}.${i}.0/24"
    NODEIP="100.${CLUSTER_ID}.255.${i}"
  else
    _hi=$(( i / 256 )); _lo=$(( i % 256 ))
    PODCIDR="100.${_hi}.${_lo}.0/24"
    NODEIP="100.$(( 128 + _hi )).${_lo}.1"
  fi

  # --- KWOK virtual node ---
  cat >> "$NODES_FILE" <<EOF
---
apiVersion: v1
kind: Node
metadata:
  name: ${NODE}
  annotations: { node.alpha.kubernetes.io/ttl: "0", kwok.x-k8s.io/node: fake }
  labels:
    beta.kubernetes.io/arch: amd64
    beta.kubernetes.io/os: linux
    kubernetes.io/arch: amd64
    kubernetes.io/hostname: ${NODE}
    kubernetes.io/os: linux
    kubernetes.io/role: agent
    node-role.kubernetes.io/agent: ""
    type: kwok
spec:
  # providerID stops the AKS cloud-node-lifecycle controller from deleting these
  # virtual nodes ("...does not exist in the cloud provider"). Without it, at scale
  # the controller deletes KWOK nodes faster than we can apply them (build 72344:
  # 10k nodes fluctuated 600-1300, never converged). A non-azure "kwok://" scheme
  # makes the Azure provider skip the instance-exists check. Verified on a live AKS
  # cluster: providerID nodes survive with 0 DeletingNode events; no-providerID
  # nodes get deleted. Harmless for the mesh tiers (<=100 nodes) too.
  providerID: kwok://${NODE}
  podCIDR: ${PODCIDR}
  podCIDRs: [${PODCIDR}]
  taints:
  - { effect: NoSchedule, key: kwok.x-k8s.io/node, value: fake }
status:
  addresses:
  - { type: InternalIP, address: ${NODEIP} }
  - { type: Hostname, address: ${NODE} }
  allocatable: { cpu: "32", memory: 256Gi, pods: "110" }
  capacity:    { cpu: "32", memory: 256Gi, pods: "110" }
  nodeInfo: { architecture: amd64, kubeletVersion: fake-kwok-${KWOK_VER}, operatingSystem: linux }
EOF

  # --- mock-cilium-agent for this node ---
  #   - prometheus.io/* annotations so a standard Prometheus scrapes per-pod metrics.
  #   - --prometheus-serve-addr=:${METRICS_PORT} exposes cilium_process_* + control-plane
  #     metrics (no collision: hostNetwork=false → own Pod IP).
  #   - serves-node label = the explicit node->agent reverse link (agent-only label).
  cat >> "$AGENTS_FILE" <<EOF
---
apiVersion: v1
kind: Pod
metadata:
  name: mock-cilium-agent-${i}
  namespace: ${AGENT_NS}
  labels:
    app: mock-cilium-agent
    mock-clustermesh/serves-node: ${NODE}
  annotations:
    prometheus.io/scrape: "true"
    prometheus.io/port: "${METRICS_PORT}"
    prometheus.io/path: /metrics
spec:
  serviceAccountName: ${AGENT_SA}
  affinity:
    nodeAffinity:
      requiredDuringSchedulingIgnoredDuringExecution:
        nodeSelectorTerms:
        - matchExpressions: [{ key: kubernetes.azure.com/cluster, operator: Exists }]
  containers:
  - name: mock-cilium-agent
    image: ${ACR_HOST}/mock-cilium-agent:${AGENT_TAG}
    command: ["/mock-cilium-agent"]
    args:
    - --identity-allocation-mode=crd
    - --ipam=kubernetes
    - --enable-l7-proxy=false
    - --enable-ipv6=false
    - --enable-bpf-clock-probe=false
    - --enable-bgp-control-plane=false
    - --enable-hubble=false
    - --cluster-name=${CLUSTER_NAME}
    - --cluster-id=${CLUSTER_ID}
    # Control-plane config inherited from the managed (Fleet/AKS) cilium-config,
    # so the mock matches the managed agent's behavior. Datapath/operator-only
    # keys are intentionally excluded (see the read block above).
    - --identity-management-mode=${IDENTITY_MGMT_MODE}
    - --max-connected-clusters=${MAX_CONNECTED_CLUSTERS}
    - --policy-default-local-cluster=${POLICY_DEFAULT_LOCAL_CLUSTER}
    - --enable-k8s-networkpolicy=${ENABLE_K8S_NETWORKPOLICY}
    - --ipam-cilium-node-update-rate=${CILIUMNODE_UPDATE_RATE}
${CM_ARG}
    - --state-dir=/var/run/mock-cilium
    - --lib-dir=/var/lib/mock-cilium
    - --log-system-load=false
    - --debug=false
    - --prometheus-serve-addr=:${METRICS_PORT}
    ports:
    - { name: prometheus, containerPort: ${METRICS_PORT} }
    env:
    - { name: MOCK_CLUSTERMESH_SKIP_ROOT_CHECK, value: "1" }
    - { name: K8S_NODE_NAME, value: ${NODE} }
    - { name: KUBE_FEATURE_GATES, value: "WatchListClient=false" }
    resources: { requests: { cpu: 100m, memory: 256Mi }, limits: { cpu: 500m, memory: 1Gi } }
    volumeMounts:
    - { name: run-state, mountPath: /var/run/mock-cilium }
    - { name: lib-state, mountPath: /var/lib/mock-cilium }
${CM_MOUNT}
  volumes:
  - { name: run-state, emptyDir: {} }
  - { name: lib-state, emptyDir: {} }
${CM_VOLUME}
  restartPolicy: OnFailure
EOF
  if [ "$(( i % 2000 ))" -eq 0 ]; then echo "   ...generated manifests for ${i}/${NODE_COUNT}"; fi
done

# Bulk apply: split each manifest file into ~500-doc chunks and apply with bounded
# parallelism (xargs -P). One kubectl process per chunk (connection reuse) instead
# of NODE_COUNT*2 separate `apply -f -` calls. Nodes FIRST — each agent references
# its kwok node via K8S_NODE_NAME. Per-chunk errors are tolerated; the readiness
# gate in deploy-mock-layer.yml is the real backstop.
apply_bulk() {
  local src="$1" tag="$2"
  # Chunk once; the retry loop below re-applies the same chunks (idempotent).
  if ! ls "${WORK}/${tag}-"*.yaml >/dev/null 2>&1; then
    awk -v dir="${WORK}" -v tag="$tag" '
      /^---/ { if (c++ % 500 == 0) n++ }
      { print > sprintf("%s/%s-%04d.yaml", dir, tag, n) }
    ' "$src"
  fi
  # Apply chunks in parallel. stdout ("created" x N) suppressed; stderr surfaced.
  # kubectl apply is idempotent, so the retry loop can re-run this to fill gaps left
  # by transient failures (see below).
  ls "${WORK}/${tag}-"*.yaml \
    | xargs -P "${MOCK_APPLY_PARALLELISM:-4}" -I{} kubectl --kubeconfig="$KUBECONFIG_FILE" apply -f {} >/dev/null \
    || echo ">>> Step 3: WARN — some ${tag} chunk(s) reported apply errors (will verify + retry)"
}

# Apply + verify WITH RETRY. The AKS pod admission webhook (aks-webhook-admission-
# controller / ccp-webhook, 10s timeout) times out under bursts of thousands of pod
# creates, and the apiserver throttles/saturates at 10k objects — so one pass leaves
# gaps (build 72334: 9963/10000 agents applied, node read throttled to 958). kubectl
# apply is idempotent, so re-applying after a settle fills the gaps once load subsides.
# Gentler default parallelism (4) reduces the initial failure rate. FAIL only if still
# short after MOCK_APPLY_MAX_ATTEMPTS. (For the multi-cluster tiers N is small, so this
# converges on attempt 1.)
attempt=1
max_attempts="${MOCK_APPLY_MAX_ATTEMPTS:-6}"
while :; do
  echo ">>> Step 3: apply attempt ${attempt}/${max_attempts} (parallelism=${MOCK_APPLY_PARALLELISM:-4})..."
  apply_bulk "$NODES_FILE" nodes
  apply_bulk "$AGENTS_FILE" agents
  sleep 15   # let the apiserver settle before counting (avoids throttled reads)
  set +e
  got_nodes=$(K get nodes -l type=kwok --no-headers 2>/dev/null | wc -l)
  got_agents=$(K -n "${AGENT_NS}" get pods -l app=mock-cilium-agent --no-headers 2>/dev/null | wc -l)
  set -e
  echo ">>> Step 3: after attempt ${attempt}: ${got_nodes}/${NODE_COUNT} node(s), ${got_agents}/${NODE_COUNT} agent(s)"
  if [ "${got_nodes:-0}" -ge "${NODE_COUNT}" ] && [ "${got_agents:-0}" -ge "${NODE_COUNT}" ]; then
    break
  fi
  if [ "$attempt" -ge "$max_attempts" ]; then
    echo "ERROR: KWOK node / mock-agent apply incomplete after ${max_attempts} attempts (${got_nodes}/${got_agents} of ${NODE_COUNT}); aborting." >&2
    exit 1
  fi
  echo ">>> Step 3: incomplete (transient AKS webhook / apiserver load) — retrying in $((attempt * 20))s..."
  sleep $((attempt * 20))
  attempt=$((attempt + 1))
done

rm -rf "${WORK}"
echo ""
echo ">>> Waiting 40s for nodes Ready + agents Running..."
sleep 40
echo "=== Virtual nodes: $(K get nodes -l type=kwok --no-headers 2>/dev/null | wc -l)/${NODE_COUNT} present (showing 5) ==="
K get nodes -l type=kwok --no-headers 2>/dev/null | head -5 || true
echo "=== Agents: $(K -n "${AGENT_NS}" get pods -l app=mock-cilium-agent --no-headers 2>/dev/null | wc -l)/${NODE_COUNT} present (showing 5) ==="
K -n "${AGENT_NS}" get pods -l app=mock-cilium-agent --no-headers 2>/dev/null | head -5 || true
echo ""
echo ">>> Done. cluster=${CLUSTER_NAME} id=${CLUSTER_ID} nodes=${NODE_COUNT}"
