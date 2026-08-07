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
#   MOCK_STATE_DIR    when set, the EXACT generated desired-state manifests
#                     (KWOK Nodes + mock-cilium-agent Pods), the already-rendered
#                     KWOK support manifests (patched kwok-controller Deployment,
#                     stage-fast, APF PriorityLevel/FlowSchema, agent RBAC) under
#                     a support/ subdir, plus a metadata.json describing them,
#                     are persisted here ATOMICALLY after a successful
#                     provisioning pass, so an out-of-band reconciler can later
#                     recreate/repair only these deterministic, owned objects
#                     without re-deriving OR re-downloading the desired state
#                     itself. Unset (default): no persistence; behavior is
#                     unchanged.
#   MOCK_RUN_ID       the pipeline RUN_ID this provisioning pass belongs to.
#                     Persisted verbatim into metadata.json's "run_id" field so
#                     an out-of-band reconciler (given an --run-id) can detect
#                     and refuse stale desired state left over from a different
#                     run. Unset (default): persisted as an empty string, and
#                     any --run-id check against it is the caller's choice.
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
MOCK_STATE_DIR="${MOCK_STATE_DIR:-}"
MOCK_RUN_ID="${MOCK_RUN_ID:-}"

K() { kubectl --kubeconfig="$KUBECONFIG_FILE" "$@"; }

# Retry an idempotent control-plane command on transient apiserver failures. A one-off
# "ServiceUnavailable"/timeout on an early `kubectl apply` would otherwise abort the
# ENTIRE cluster deploy under `set -euo pipefail` (build 72911: mesh-1 died on a single
# ServiceUnavailable applying the ServiceAccount, failing the whole n=5 stage at
# MOCK_DEPLOY_MAX_FAILURES=0 while the other 4 clusters were fine). Step 3 (node/agent
# apply) has its own attempt loop; kretry covers the Step 1-2 setup calls. Commands MUST
# be file-based/idempotent — never `apply -f -` with a heredoc, whose stdin can't be
# replayed across attempts.
kretry() {
  local _a=1 _max="${MOCK_SETUP_MAX_ATTEMPTS:-5}" _rc=0
  case "$_max" in ''|*[!0-9]*) _max=5;; esac   # guard: non-numeric override -> default
  while :; do
    _rc=0; "$@" && return 0 || _rc=$?
    [ "$_a" -ge "$_max" ] && { echo "ERROR: '$*' failed after ${_max} attempts (rc=${_rc})." >&2; return "$_rc"; }
    echo ">>> transient failure (rc=${_rc}) on '$*'; retry ${_a}/${_max} in $((_a * 5))s..." >&2
    sleep $((_a * 5)); _a=$((_a + 1))
  done
}

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
        # Pin to real AKS nodes (kubernetes.azure.com/cluster), but keep OFF the
        # dedicated Prometheus node (labeled prometheus=true) so the CL2 monitoring
        # stack always has room there. See the agent affinity below for the rationale.
        d['spec']['template']['spec']['affinity'] = {'nodeAffinity': {
            'requiredDuringSchedulingIgnoredDuringExecution': {'nodeSelectorTerms': [
                {'matchExpressions': [
                    {'key': 'kubernetes.azure.com/cluster', 'operator': 'Exists'},
                    {'key': 'prometheus', 'operator': 'DoesNotExist'}]}]}}}
yaml.safe_dump_all(docs, open(dst, 'w'), default_flow_style=False)
PY
kretry K apply -f "${WORK}/kwok-patched.yaml" >/dev/null
kretry K apply -f "${WORK}/stage-fast.yaml" >/dev/null
MOCK_SETUP_MAX_ATTEMPTS=2 kretry K -n kube-system rollout status deploy/kwok-controller --timeout=120s

# ---------------------------------------------------------------------------
# STEP 1.5: APF protection for kwok-controller
#
# kwok-controller authenticates as a generic ServiceAccount, so its pod- and
# node-status PATCHes fall into the built-in `workload-low` API Priority &
# Fairness (APF) class — the SAME class the churn workload floods. Under
# mesh+churn at 2500+ nodes/cluster the apiserver starves workload-low
# (telescope build 72911, n2 mesh-1: ~695k time-out + ~213k queue-full rejects
# on priority_level=workload-low), so kwok-controller could not set pods Ready
# and ~40% of pods stayed Running-but-NotReady for the whole run — while mesh-2
# (far less workload-low pressure) stayed 2500/2500. Diagnosed entirely from the
# already-scraped KSM + apiserver_flowcontrol_* metrics in the prom snapshot.
#
# Give kwok-controller a DEDICATED priority level with guaranteed concurrency so
# its control-loop writes are never starved by the workload it simulates. This is
# a mock-framework fix (kwok is our SIMULATOR, not part of the system under test),
# so it does NOT mask a real Cilium scale limit — the mock-cilium-agents stay in
# workload-low on purpose, so genuine mesh-sync saturation still shows up.
echo ">>> Step 1.5: APF PriorityLevelConfiguration + FlowSchema for kwok-controller..."
cat > "${WORK}/kwok-apf.yaml" <<'EOF'
apiVersion: flowcontrol.apiserver.k8s.io/v1
kind: PriorityLevelConfiguration
metadata:
  name: kwok-controller
spec:
  type: Limited
  limited:
    # Guaranteed seats for kwok's control-loop writes. kwok is mock INFRA — in a real
    # cluster the kubelet/node status updates it stands in for get privileged APF, not
    # workload-low — so reserving capacity CORRECTS an artifact rather than distorting
    # the test. lendablePercent returns half the seats to the shared pool when kwok is
    # idle, so the scale-test workload isn't starved of concurrency between bursts.
    nominalConcurrencyShares: 50
    lendablePercent: 50
    limitResponse:
      # Queue (not Reject) so status-PATCH bursts wait instead of 429ing. Combined with
      # distinguisherMethod ByNamespace (below), kwok's per-namespace pod-status writes
      # shuffle-shard across all 64 queues instead of piling into one flow's ~6-queue hand.
      type: Queue
      queuing:
        queues: 64
        handSize: 6
        queueLengthLimit: 50
---
apiVersion: flowcontrol.apiserver.k8s.io/v1
kind: FlowSchema
metadata:
  name: kwok-controller
spec:
  priorityLevelConfiguration:
    name: kwok-controller
  # Lower precedence value = evaluated first; 500 beats built-in workload-high
  # (1000) / workload-low (9000) / global-default (9900). Only the kwok-controller
  # SA matches these rules, so nothing else is affected.
  matchingPrecedence: 500
  distinguisherMethod:
    # ByNamespace so kwok's pod-status PATCHes (across 250-500 workload namespaces)
    # fan out over the queue set; cluster-scoped node writes share the empty-ns flow.
    type: ByNamespace
  rules:
    - subjects:
        - kind: ServiceAccount
          serviceAccount:
            name: kwok-controller
            namespace: kube-system
      resourceRules:
        # clusterScope:true is load-bearing — kwok patches nodes/status (cluster-scoped).
        - verbs: ["*"]
          apiGroups: ["*"]
          resources: ["*"]
          clusterScope: true
          namespaces: ["*"]
      nonResourceRules:
        - verbs: ["*"]
          nonResourceURLs: ["*"]
EOF
kretry K apply -f "${WORK}/kwok-apf.yaml" >/dev/null

# ---------------------------------------------------------------------------
# STEP 2: RBAC for the agents (ServiceAccount + cluster-admin; tighten later)
# ---------------------------------------------------------------------------
echo ">>> Step 2: RBAC (${AGENT_NS}/${AGENT_SA})..."
cat > "${WORK}/rbac.yaml" <<EOF
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
kretry K apply -f "${WORK}/rbac.yaml" >/dev/null

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
CM_ARG=""; CM_MOUNT=""; CM_VOLUME=""; CONSUME_CLUSTERMESH_ACTIVE=false
if [[ "${CONSUME_CLUSTERMESH}" == "true" ]]; then
  if ! K -n kube-system get secret cilium-clustermesh >/dev/null 2>&1; then
    echo "ERROR: CONSUME_CLUSTERMESH=true but kube-system/cilium-clustermesh is missing; refusing a publish-only hollow run." >&2
    exit 1
  fi
  echo ">>> Step 2.5: Wiring clustermesh CONSUME path (copying secrets -> ${AGENT_NS})..."
  STRIP='del(.metadata.namespace,.metadata.resourceVersion,.metadata.uid,.metadata.creationTimestamp,.metadata.ownerReferences,.metadata.managedFields,.metadata.annotations,.status)'
  # Copy pipeline as a function so kretry can replay it (each attempt re-runs the
  # `get`, so unlike a heredoc there's no consumed-stdin problem). A transient
  # apiserver failure mid-copy would otherwise silently skip a REQUIRED consume
  # secret (the old code WARNed "not found" + continued), leaving agents running but
  # NOT consuming mesh state — a hollow run that still "passes". Every source
  # secret is therefore mandatory when consume mode is requested.
  copy_secret() { K -n kube-system get secret "$1" -o json 2>/dev/null | jq "${STRIP}" | K -n "${AGENT_NS}" apply -f - >/dev/null 2>&1; }
  for s in cilium-clustermesh clustermesh-apiserver-remote-cert clustermesh-apiserver-local-cert cilium-root-ca.crt; do
    if kretry copy_secret "$s"; then
      echo "      copied secret ${s}"
    else
      echo "ERROR: required consume secret ${s} was not copied after retries; refusing to start hollow mock agents." >&2
      exit 1
    fi
  done
  CM_ARG="    - --clustermesh-config=/var/lib/cilium/clustermesh"
  CM_MOUNT="    - { name: clustermesh-secrets, mountPath: /var/lib/cilium/clustermesh, readOnly: true }"
  CM_VOLUME=$(cat <<'YAML'
  - name: clustermesh-secrets
    projected:
      defaultMode: 256
      sources:
      - secret: { name: cilium-clustermesh }
      - secret: { name: clustermesh-apiserver-remote-cert, items: [ { key: tls.key, path: common-etcd-client.key }, { key: tls.crt, path: common-etcd-client.crt } ] }
      - secret: { name: cilium-root-ca.crt, items: [ { key: ca.crt, path: common-etcd-client-ca.crt } ] }
      - secret: { name: clustermesh-apiserver-local-cert, items: [ { key: tls.key, path: local-etcd-client.key }, { key: tls.crt, path: local-etcd-client.crt } ] }
      - secret: { name: cilium-root-ca.crt, items: [ { key: ca.crt, path: local-etcd-client-ca.crt } ] }
YAML
)
  # Recorded into metadata.json (STEP 3.5 below) so an out-of-band reconciler
  # knows whether it must also verify/repair the 4 copied consume secrets --
  # it never guesses this from CONSUME_CLUSTERMESH alone, since that only
  # reflects the OPERATOR's intent, not whether the source secret actually
  # existed here (this "if" already checked that).
  CONSUME_CLUSTERMESH_ACTIVE=true
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
# For a >250-nodes/cluster MESH (MOCK_MESH_STRIDE set) the podCIDR/nodeIP use a
# GLOBAL index (cluster_id*stride + node) that must stay < 32768 so podCIDR octet2
# (gi/256) stays in 0..127 and nodeIP octet2 (128+gi/256) stays in 128..255.
# Guard ONLY when scheme 2 is actually used (NODE_COUNT>250 AND stride set) so a
# <=250 run that happens to inherit MOCK_MESH_STRIDE isn't rejected spuriously.
if [ "${NODE_COUNT}" -gt 250 ] && [ -n "${MOCK_MESH_STRIDE:-}" ]; then
  _max_gi=$(( CLUSTER_ID * MOCK_MESH_STRIDE + NODE_COUNT - 1 ))
  if [ "${NODE_COUNT}" -gt "${MOCK_MESH_STRIDE}" ]; then
    echo "ERROR: NODE_COUNT=${NODE_COUNT} exceeds MOCK_MESH_STRIDE=${MOCK_MESH_STRIDE} (per-cluster index would overflow into the next cluster's block)." >&2
    exit 1
  fi
  if [ "${_max_gi}" -ge 32768 ]; then
    echo "ERROR: global index cluster_id(${CLUSTER_ID})*stride(${MOCK_MESH_STRIDE})+nodes exceeds 32768 — reduce clusters/stride." >&2
    exit 1
  fi
fi
for i in $(seq 0 $((NODE_COUNT - 1))); do
  NODE="kwok-node-${i}"
  # Globally-unique podCIDR + nodeIP per node in the synthetic 100.0.0.0/8 space
  # (never routed; phantom-pod identifiers) so they never overlap the real VNet
  # (10.0.0.0/8). The node index needs TWO octets once NODE_COUNT>256:
  #   * NODE_COUNT<=250 (multi-cluster mesh tiers): 100.<cluster_id>.<i>.0/24 —
  #     cluster-id in octet 2 makes Pod IPs unique ACROSS the mesh so remote
  #     backends don't collide; nodeIP 100.<cid>.255.<i> (the .255 octet avoids
  #     the podCIDRs at 0..NODE_COUNT).
  #   * NODE_COUNT>250 + MOCK_MESH_STRIDE set (multi-cluster mesh, >250/cluster):
  #     a GLOBAL index gi=<cluster_id>*<stride>+<i> gives every (cluster,node) a
  #     unique /24 100.<gi/256>.<gi%256>.0/24 across the WHOLE mesh (stride>=nodes
  #     keeps clusters' ranges disjoint); nodeIP in the disjoint 100.128+.x block.
  #   * NODE_COUNT>250, no stride (single-cluster baseline): a 2-octet LOCAL index
  #     100.<i/256>.<i%256>.0/24 (drops cluster-id — single-cluster only).
  if [ "${NODE_COUNT}" -le 250 ]; then
    PODCIDR="100.${CLUSTER_ID}.${i}.0/24"
    NODEIP="100.${CLUSTER_ID}.255.${i}"
  elif [ -n "${MOCK_MESH_STRIDE:-}" ]; then
    _gi=$(( CLUSTER_ID * MOCK_MESH_STRIDE + i ))
    _hi=$(( _gi / 256 )); _lo=$(( _gi % 256 ))
    PODCIDR="100.${_hi}.${_lo}.0/24"
    NODEIP="100.$(( 128 + _hi )).${_lo}.1"
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
  annotations: { kwok.x-k8s.io/node: fake }
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
        # Run on real AKS nodes (kubernetes.azure.com/cluster exists) but NEVER on the
        # dedicated Prometheus node (labeled prometheus=true). At 10k agents on a single
        # cluster the agents would otherwise pack every real node to max-pods, including
        # the prompool, starving CL2's prometheus stack (operator + prometheus-k8s could
        # not schedule -> 8min late -> blew CL2's prometheus-ready budget, build 72558).
        # Excluding one small prompool is free (10k agents fit on the remaining pool).
        - matchExpressions:
          - { key: kubernetes.azure.com/cluster, operator: Exists }
          - { key: prometheus, operator: DoesNotExist }
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

# ---------------------------------------------------------------------------
# STEP 3.5: persist the desired-state snapshot (optional).
#
# Copies the EXACT manifests just applied above (not re-derived — byte-for-byte
# the same $NODES_FILE / $AGENTS_FILE this run generated), the EXACT already-
# rendered KWOK support manifests from Steps 1/1.5/2 (kwok-patched.yaml,
# stage-fast.yaml, kwok-apf.yaml, rbac.yaml — never redownloaded/rederived by
# a later reconciler), plus a metadata.json describing this deploy, into
# MOCK_STATE_DIR. This lets a separate reconciler recreate/repair only these
# deterministic, owned objects later (e.g. after node churn, attrition, or a
# kwok-controller crash) WITHOUT re-deriving the desired state (podCIDR/nodeIP
# scheme, cluster identity, inherited cilium-config, ...) or re-fetching the
# support manifests — both only happen here, once, right after a
# verified-successful apply.
#
# Published safely, NOT via an instantaneous atomic swap: built in a sibling
# temp dir on the SAME filesystem as MOCK_STATE_DIR (so a crash/interrupt
# mid-copy only abandons the temp dir, never corrupts a prior snapshot), then
# put in place with two renames (old-dir-aside, then temp-dir-into-place).
# Each individual rename(2) is atomic, but the two-step swap is NOT gap-free —
# a reader could observe MOCK_STATE_DIR transiently absent between them. That
# is fine here: this run-scoped path ($HOME/.kube/mock-layer-state/<run_id>/
# <role>, see deploy-mock-layer.yml) has NO concurrent reader during
# provisioning — deploy-mock-layer.yml clears this exact path before invoking
# this script, and the only other consumer (mock_layer_reconcile.py) runs in a
# LATER, separate pipeline step, strictly after this script has already
# exited. Do not rely on this dance for true concurrent-reader safety if that
# assumption ever changes.
if [[ -n "${MOCK_STATE_DIR}" ]]; then
  echo ">>> Step 3.5: persisting desired-state manifests to ${MOCK_STATE_DIR}..."
  STATE_PARENT="$(dirname "${MOCK_STATE_DIR}")"
  mkdir -p "${STATE_PARENT}"
  STATE_TMP="$(mktemp -d "${STATE_PARENT}/.mock-layer-state.XXXXXX")"
  cp "${NODES_FILE}" "${STATE_TMP}/nodes.yaml"
  cp "${AGENTS_FILE}" "${STATE_TMP}/agents.yaml"
  mkdir -p "${STATE_TMP}/support"
  cp "${WORK}/kwok-patched.yaml" "${STATE_TMP}/support/kwok-controller.yaml"
  cp "${WORK}/stage-fast.yaml"   "${STATE_TMP}/support/stage-fast.yaml"
  cp "${WORK}/kwok-apf.yaml"     "${STATE_TMP}/support/kwok-apf.yaml"
  cp "${WORK}/rbac.yaml"         "${STATE_TMP}/support/rbac.yaml"
  python3 - "${STATE_TMP}/metadata.json" <<PY
import json, sys
dst = sys.argv[1]
metadata = {
    "schema_version": 2,
    "generated_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
    "run_id": "${MOCK_RUN_ID}",
    "cluster_name": "${CLUSTER_NAME}",
    "cluster_id": "${CLUSTER_ID}",
    "node_count": ${NODE_COUNT},
    "agent_namespace": "${AGENT_NS}",
    "agent_service_account": "${AGENT_SA}",
    "agent_label_selector": "app=mock-cilium-agent",
    "node_label_selector": "type=kwok",
    "serves_node_label": "mock-clustermesh/serves-node",
    "kwok_node_annotation": {"key": "kwok.x-k8s.io/node", "value": "fake"},
    "acr_host": "${ACR_HOST}",
    "agent_tag": "${AGENT_TAG}",
    "agent_image": "${ACR_HOST}/mock-cilium-agent:${AGENT_TAG}",
    "metrics_port": ${METRICS_PORT},
    "kwok_version": "${KWOK_VER}",
    "consume_clustermesh": $( [ "${CONSUME_CLUSTERMESH_ACTIVE}" = "true" ] && echo True || echo False ),
    "node_manifest": "nodes.yaml",
    "agent_manifest": "agents.yaml",
    "support_manifest_dir": "support",
    "support_manifests": {
        "kwok_controller": "support/kwok-controller.yaml",
        "stage": "support/stage-fast.yaml",
        "apf": "support/kwok-apf.yaml",
        "rbac": "support/rbac.yaml",
    },
}
with open(dst, "w", encoding="utf-8") as fh:
    json.dump(metadata, fh, indent=2, sort_keys=True)
    fh.write("\n")
PY
  if [ -e "${MOCK_STATE_DIR}" ]; then
    rm -rf "${MOCK_STATE_DIR}.stale"
    mv -T "${MOCK_STATE_DIR}" "${MOCK_STATE_DIR}.stale"
  fi
  mv -T "${STATE_TMP}" "${MOCK_STATE_DIR}"
  rm -rf "${MOCK_STATE_DIR}.stale"
  echo ">>> Step 3.5: persisted nodes.yaml + agents.yaml + support/ + metadata.json to ${MOCK_STATE_DIR}"
fi

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
