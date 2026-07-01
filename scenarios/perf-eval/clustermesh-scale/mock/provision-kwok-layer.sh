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
# Read the Fleet-assigned cluster identity (do NOT hardcode).
# ---------------------------------------------------------------------------
CLUSTER_NAME="$(K -n kube-system get cm cilium-config -o jsonpath='{.data.cluster-name}')"
CLUSTER_ID="$(K -n kube-system get cm cilium-config -o jsonpath='{.data.cluster-id}')"
if [[ -z "${CLUSTER_NAME}" || -z "${CLUSTER_ID}" || "${CLUSTER_ID}" == "0" ]]; then
  echo "ERROR: cluster not Fleet-meshed (cluster-name='${CLUSTER_NAME}' cluster-id='${CLUSTER_ID}')." >&2
  echo "       Apply the Fleet ClusterMesh profile first." >&2
  exit 1
fi
echo ">>> Fleet identity: cluster-name=${CLUSTER_NAME} cluster-id=${CLUSTER_ID}"

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
echo ">>> Step 3: Creating ${NODE_COUNT} virtual node(s) + agent(s)..."
for i in $(seq 0 $((NODE_COUNT - 1))); do
  NODE="kwok-node-${i}"
  # Globally-unique podCIDR per (cluster, node): 100.<cluster_id>.<node>.0/24.
  # The cluster-id in the 2nd octet makes Pod IPs unique ACROSS the mesh (not just
  # within a cluster), so cross-cluster service backends don't collide — a remote
  # cluster's pods have distinct IPs from local pods. Uses the 100.0.0.0/8 synthetic
  # space (never routed; these are phantom-pod identifiers) to avoid any overlap with
  # the real VNet (10.0.0.0/8) node/pod/service subnets.
  PODCIDR="100.${CLUSTER_ID}.${i}.0/24"
  # Distinct InternalIP per node. By default KWOK assigns the kwok-controller's own
  # Pod IP (--node-ip=$(POD_IP)) to EVERY node, so all CiliumNodes would propagate the
  # same node IP cross-cluster. Setting status.addresses per node (KWOK respects it)
  # gives each virtual node a unique, globally-unique node IP. Uses the .255 third
  # octet so it never overlaps the podCIDRs (which use 0..NODE_COUNT).
  NODEIP="100.${CLUSTER_ID}.255.${i}"

  # --- KWOK virtual node ---
  K apply -f - >/dev/null <<EOF
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
  K apply -f - >/dev/null <<EOF
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
  echo "   ${NODE} (podCIDR ${PODCIDR}) + mock-cilium-agent-${i}"
done

rm -rf "${WORK}"
echo ""
echo ">>> Waiting 40s for nodes Ready + agents Running..."
sleep 40
echo "=== Virtual nodes ==="
K get nodes -l type=kwok -o custom-columns='NAME:.metadata.name,STATUS:.status.conditions[-1].type,PODCIDR:.spec.podCIDR'
echo "=== Agents ==="
K -n "${AGENT_NS}" get pods -l app=mock-cilium-agent -o custom-columns='NAME:.metadata.name,READY:.status.phase,NODE_ENV:.spec.containers[0].env[1].value'
echo ""
echo ">>> Done. cluster=${CLUSTER_NAME} id=${CLUSTER_ID} nodes=${NODE_COUNT}"
