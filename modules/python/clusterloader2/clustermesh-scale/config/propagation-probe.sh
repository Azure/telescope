#!/bin/bash
# propagation-probe.sh
#
# Host-side propagation + connectivity probe orchestrator. Invoked by
# execute.yml's launch_propagation_probe (NOT by CL2 Method:Exec — the
# CL2 container has only one kubeconfig mounted, but this script needs
# all N to poll peer state and run cross-cluster curls).
#
# What it does (per probe iteration):
#   1. Pick a random source cluster.
#   2. Create a probe pod (agnhost serve-hostname) in the source cluster's
#      pre-annotated clustermesh-probe-1 namespace (annotation done by
#      CL2 scenario's AnnotateNamespacesForGlobalSync step).
#   3. Wait for pod to get an IP and reach Ready, record timestamps:
#      t_apply, t_scheduled, t_ip_assigned, t_pod_ready, t_local_ep.
#   4. For each sampled peer (cap PEER_SAMPLE_MAX, random subset at large N):
#        - poll peer's cilium-agent BPF ipcache for pod IP -> t_peer_ipcache
#        - poll peer's cilium identities for our unique label UUID -> t_peer_identity
#        - poll peer's CEP CRDs for the pod IP -> t_peer_cep
#        - if connectivity enabled: from a peer-side curl pod, resolve+curl
#          the GLOBAL SERVICE DNS name (not pod IP), record HTTP status +
#          returned hostname + RTT.
#   5. Delete the probe pod.
#   6. Append per-probe-per-peer rows to PropagationTimings.jsonl and
#      ConnectivityResults.jsonl in OUTPUT_DIR.
#
# Args (positional):
#   $1  PROBE_COUNT            number of probes (e.g. 20)
#   $2  PROBE_INTERVAL_S       seconds between consecutive probes (e.g. 30)
#   $3  PROBE_NS               annotated namespace to create probe pods in
#                              (must match the CL2 scenario's namespace
#                              prefix-1, e.g. clustermesh-probe-1)
#   $4  PEER_SAMPLE_MAX        cap on peers polled per probe (e.g. 20)
#   $5  PEER_TIMEOUT_S         per-peer wait deadline (e.g. 60)
#   $6  CLUSTERS_JSON          path to augmented clusters JSON
#                              ($HOME/.kube/clustermesh-clusters.json)
#   $7  OUTPUT_DIR             dir for JSONL outputs
#   $8  ENABLE_CONNECTIVITY    "true" to also do cross-peer DNS+curl
#
# Output JSONL (one line per probe per peer):
#   PropagationTimings.jsonl rows have shape:
#     {probe_id, probe_ns, src_cluster, peer_cluster, label_uuid,
#      pod_ip, pod_hostname, t_apply_ns, t_scheduled_ns, t_ip_assigned_ns,
#      t_pod_ready_ns, t_local_ep_ns, t_peer_ipcache_ns,
#      t_peer_identity_ns, t_peer_cep_ns, peer_timed_out}
#   ConnectivityResults.jsonl rows (if ENABLE_CONNECTIVITY=true):
#     {probe_id, src_cluster, peer_cluster, global_service_dns,
#      t_curl_attempt_ns, curl_rc, curl_http_status, curl_total_seconds,
#      returned_hostname, returned_hostname_matches_src_pod}
#
# Cilium-agent commands tried (in order, gracefully degrades):
#   ipcache:  `cilium-dbg bpf ipcache list` -> `cilium bpf ipcache list`
#   identity: `cilium identity list -o json` -> `cilium-dbg identity list -o json`
#
# AKS-managed Cilium pod selector tried (in order):
#   k8s-app=cilium -> app.kubernetes.io/name=cilium -> name=cilium

set -uo pipefail

PROBE_COUNT="${1:?PROBE_COUNT required}"
PROBE_INTERVAL_S="${2:?PROBE_INTERVAL_S required}"
PROBE_NS="${3:?PROBE_NS required}"
PEER_SAMPLE_MAX="${4:?PEER_SAMPLE_MAX required}"
PEER_TIMEOUT_S="${5:?PEER_TIMEOUT_S required}"
CLUSTERS_JSON="${6:?CLUSTERS_JSON required}"
OUTPUT_DIR="${7:?OUTPUT_DIR required}"
ENABLE_CONNECTIVITY="${8:-false}"

# Opt-in extensions (env-toggled, default OFF — existing scenarios unaffected):
#   ENABLE_REMOVE_PROBE=true: after add probe completes, DELETE the probe pod
#     on src and poll each peer's BPF ipcache UNTIL the IP disappears.
#     Measures stale-state risk — peer continues routing to dead pods for
#     how long after pod delete? Adds delta_remove_ms per peer to JSONL.
#   ENABLE_FIRST_PACKET_PROBE=true: after src pod ready, IMMEDIATELY start
#     curling global Service DNS from each peer in tight loop. Record
#     t_peer_first_success_ns = first 200 OK from peer that returns the
#     src pod's hostname (proves cross-cluster routing). Bridges gap
#     between ipcache propagation (~35s) and user-perceived "service
#     works" latency. Adds delta_first_packet_ms per peer to ConnectivityResults.
ENABLE_REMOVE_PROBE="${ENABLE_REMOVE_PROBE:-false}"
ENABLE_FIRST_PACKET_PROBE="${ENABLE_FIRST_PACKET_PROBE:-false}"
ENABLE_SERVICE_BACKEND_PROBE="${ENABLE_SERVICE_BACKEND_PROBE:-false}"
REMOVE_PROBE_TIMEOUT_S="${REMOVE_PROBE_TIMEOUT_S:-60}"
FIRST_PACKET_PROBE_TIMEOUT_S="${FIRST_PACKET_PROBE_TIMEOUT_S:-60}"
SERVICE_BACKEND_PROBE_TIMEOUT_S="${SERVICE_BACKEND_PROBE_TIMEOUT_S:-60}"

PROP_OUT="${OUTPUT_DIR}/PropagationTimings.jsonl"
CONN_OUT="${OUTPUT_DIR}/ConnectivityResults.jsonl"
REMOVE_OUT="${OUTPUT_DIR}/RemovePropagationTimings.jsonl"
mkdir -p "$OUTPUT_DIR"
: > "$PROP_OUT"
[ "$ENABLE_CONNECTIVITY" = "true" ] && : > "$CONN_OUT"
[ "$ENABLE_REMOVE_PROBE" = "true" ] && : > "$REMOVE_OUT"

if [ ! -f "$CLUSTERS_JSON" ]; then
  echo "FATAL: CLUSTERS_JSON $CLUSTERS_JSON not found" >&2
  exit 1
fi

CLUSTER_COUNT=$(jq 'length' < "$CLUSTERS_JSON")
if [ "$CLUSTER_COUNT" -lt 2 ]; then
  echo "FATAL: need >=2 clusters, found $CLUSTER_COUNT" >&2
  exit 1
fi

# MS-approved container images (avoid CSSC external-registry policy violations).
# - CURL_IMAGE: cbl-mariner base has curl pre-installed; used by the peer-side
#   connectivity probe client pod.
# - PROBE_IMAGE: pause:3.6 — same MCR-approved image already used by the
#   workload Deployment templates (event-throughput-deployment.yaml,
#   scale-test-deployment.yaml). Pause does NOT serve HTTP, but the
#   propagation probe doesn't need it to — we only need the probe pod
#   to exist, get an IP from CNI, register a Cilium identity, and
#   propagate to peers via kvstore. Connectivity validation hits the
#   long-running nginx-based backend Deployment (which is a different
#   pod, behind the global Service).
CURL_IMAGE="mcr.microsoft.com/cbl-mariner/base/core:2.0"
PROBE_IMAGE="mcr.microsoft.com/oss/kubernetes/pause:3.6"
# When ENABLE_FIRST_PACKET_PROBE=true the probe pod needs to serve HTTP so
# the peer-side curl can verify the response actually came from THIS specific
# pod (returns its hostname). nginx (cbl-mariner) is MCR-approved and already
# used for the backend Deployment template. Adds ~50MB image vs pause's
# single-digit MB; acceptable for the 10-30 probes/run we do.
PROBE_HTTP_IMAGE="mcr.microsoft.com/cbl-mariner/base/nginx:1"

# Global Service DNS name — resolved at runtime from the first Service
# in PROBE_NS on the first cluster (CL2 names objects with 0- or 1-
# based indexing depending on version; resolving at runtime avoids that
# brittleness). Falls back to a sensible default if discovery fails so
# the connectivity probe still has SOMETHING to try.
GLOBAL_SVC_DNS=""
discover_global_svc_dns() {
  local _kc _ctx _svc
  _kc=$(jq -r ".[0].kubeconfig" < "$CLUSTERS_JSON")
  _ctx=$(jq -r ".[0].name" < "$CLUSTERS_JSON")
  # 60s budget — CL2 needs time to create the workload Service before
  # the prewait expires + this fires.
  local _start; _start=$(date +%s)
  while true; do
    _svc=$(KUBECONFIG="$_kc" kubectl --context "$_ctx" -n "$PROBE_NS" \
      get svc -l group=clustermesh-propagation-probe \
      -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo "")
    if [ -n "$_svc" ]; then
      GLOBAL_SVC_DNS="${_svc}.${PROBE_NS}.svc.cluster.local:80"
      echo "[probe] resolved global Service DNS: $GLOBAL_SVC_DNS"
      return 0
    fi
    local _now; _now=$(date +%s)
    if [ $((_now - _start)) -ge 60 ]; then
      echo "[probe] WARN: could not discover global Service in 60s; connectivity probes will skip"
      GLOBAL_SVC_DNS=""
      return 1
    fi
    sleep 2
  done
}

echo "[probe] start: count=$PROBE_COUNT interval=${PROBE_INTERVAL_S}s ns=$PROBE_NS peer_sample_max=$PEER_SAMPLE_MAX peer_timeout=${PEER_TIMEOUT_S}s connectivity=$ENABLE_CONNECTIVITY clusters=$CLUSTER_COUNT"

# Preflight: verify cilium-agent + the bpf/identity commands we depend on
# are accessible inside an AKS-managed Cilium agent pod. If they're not,
# the probe would silently produce empty JSONLs — better to fail loudly
# with a clear message so we know to iterate the script instead of
# wondering why no propagation timestamps showed up in Kusto.
preflight_cilium_commands() {
  local _kc _ctx _cil
  _kc=$(jq -r ".[0].kubeconfig" < "$CLUSTERS_JSON")
  _ctx=$(jq -r ".[0].name" < "$CLUSTERS_JSON")
  echo "[probe] preflight: checking cilium-agent commands on $_ctx..."
  _cil=$(find_cilium_pod "$_kc" "$_ctx")
  if [ -z "$_cil" ]; then
    echo "[probe] PREFLIGHT FAIL: no cilium-agent pod found on $_ctx in kube-system (tried selectors k8s-app=cilium, app.kubernetes.io/name=cilium, name=cilium). Aborting probe." >&2
    return 1
  fi
  echo "[probe] preflight: cilium-agent pod = $_cil"
  # Test bpf ipcache list. AKS-managed Cilium agent is DISTROLESS — no
  # `sh` binary inside the container. Invoke each candidate command
  # directly via kubectl exec; capture stdout+stderr separately.
  local _ipcache_out _ipcache_err
  _ipcache_out=$(KUBECONFIG="$_kc" kubectl --context "$_ctx" -n kube-system exec "$_cil" -c cilium-agent -- \
    cilium-dbg bpf ipcache list 2>/dev/null | head -5)
  if [ -z "$_ipcache_out" ]; then
    # Fallback to older binary name.
    _ipcache_out=$(KUBECONFIG="$_kc" kubectl --context "$_ctx" -n kube-system exec "$_cil" -c cilium-agent -- \
      cilium bpf ipcache list 2>/dev/null | head -5)
  fi
  if [ -z "$_ipcache_out" ]; then
    # One more diagnostic call WITH stderr captured to give a useful failure msg.
    _ipcache_err=$(KUBECONFIG="$_kc" kubectl --context "$_ctx" -n kube-system exec "$_cil" -c cilium-agent -- \
      cilium-dbg bpf ipcache list 2>&1 | head -3)
    echo "[probe] PREFLIGHT FAIL: neither cilium-dbg nor cilium bpf ipcache list returns output on $_cil." >&2
    echo "[probe] cilium-dbg stderr/stdout sample: $_ipcache_err" >&2
    return 1
  fi
  echo "[probe] preflight: bpf ipcache list works (sample: $(echo "$_ipcache_out" | head -1 | head -c 100))"
  # Test identity list -o json
  local _id_out
  _id_out=$(KUBECONFIG="$_kc" kubectl --context "$_ctx" -n kube-system exec "$_cil" -c cilium-agent -- \
    cilium identity list -o json 2>/dev/null | head -1)
  if [ -z "$_id_out" ]; then
    _id_out=$(KUBECONFIG="$_kc" kubectl --context "$_ctx" -n kube-system exec "$_cil" -c cilium-agent -- \
      cilium-dbg identity list -o json 2>/dev/null | head -1)
  fi
  if [ -z "$_id_out" ]; then
    echo "[probe] PREFLIGHT WARN: identity list -o json may not work; identity timestamps will be 0. Continuing anyway."
  else
    echo "[probe] preflight: identity list works"
  fi
  return 0
}

# Find cilium-agent pod on a cluster (any node — ipcache is synced).
find_cilium_pod() {
  local _kc="$1" _ctx="$2"
  for sel in 'k8s-app=cilium' 'app.kubernetes.io/name=cilium' 'name=cilium'; do
    local _pod
    _pod=$(KUBECONFIG="$_kc" kubectl --context "$_ctx" -n kube-system get pod \
      -l "$sel" -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
    if [ -n "$_pod" ]; then echo "$_pod"; return 0; fi
  done
  return 1
}

# Wait for pod_ip on a context; return 0 + sets POD_IP, else 1.
wait_pod_ip() {
  local _kc="$1" _ctx="$2" _ns="$3" _pod="$4" _deadline_s="$5"
  local _start _now
  _start=$(date +%s)
  POD_IP=""
  while true; do
    POD_IP=$(KUBECONFIG="$_kc" kubectl --context "$_ctx" -n "$_ns" \
      get pod "$_pod" -o jsonpath='{.status.podIP}' 2>/dev/null || echo "")
    [ -n "$POD_IP" ] && return 0
    _now=$(date +%s)
    if [ $((_now - _start)) -ge "$_deadline_s" ]; then return 1; fi
    sleep 0.5
  done
}

# Wait for pod Ready. Sets T_POD_READY_NS or 0.
wait_pod_ready() {
  local _kc="$1" _ctx="$2" _ns="$3" _pod="$4" _deadline_s="$5"
  local _start _now
  _start=$(date +%s)
  while true; do
    local _ready
    _ready=$(KUBECONFIG="$_kc" kubectl --context "$_ctx" -n "$_ns" \
      get pod "$_pod" -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}' 2>/dev/null || echo "")
    if [ "$_ready" = "True" ]; then
      T_POD_READY_NS=$(date +%s%N); return 0
    fi
    _now=$(date +%s)
    if [ $((_now - _start)) -ge "$_deadline_s" ]; then
      T_POD_READY_NS=0; return 1
    fi
    sleep 0.5
  done
}

# Wait for source cluster's local cilium-agent endpoint list to include
# the pod IP. Sets T_LOCAL_EP_NS or 0. AKS-managed Cilium is distroless;
# invoke binaries directly without sh -c wrapper.
wait_local_endpoint() {
  local _kc="$1" _ctx="$2" _pod_ip="$3" _deadline_s="$4"
  local _start _now _cil _out
  _start=$(date +%s)
  _cil=$(find_cilium_pod "$_kc" "$_ctx") || { T_LOCAL_EP_NS=0; return 1; }
  while true; do
    _out=$(KUBECONFIG="$_kc" kubectl --context "$_ctx" -n kube-system exec "$_cil" -c cilium-agent -- \
      cilium endpoint list 2>/dev/null || true)
    if [ -z "$_out" ]; then
      _out=$(KUBECONFIG="$_kc" kubectl --context "$_ctx" -n kube-system exec "$_cil" -c cilium-agent -- \
        cilium-dbg endpoint list 2>/dev/null || true)
    fi
    if echo "$_out" | grep -qF "$_pod_ip"; then
      T_LOCAL_EP_NS=$(date +%s%N); return 0
    fi
    _now=$(date +%s)
    if [ $((_now - _start)) -ge "$_deadline_s" ]; then
      T_LOCAL_EP_NS=0; return 1
    fi
    sleep 1
  done
}

# Wait for peer ipcache to include pod IP. Sets T_PEER_IPCACHE_NS or 0.
wait_peer_ipcache() {
  local _kc="$1" _ctx="$2" _pod_ip="$3" _deadline_s="$4"
  local _start _now _cil _out
  _start=$(date +%s)
  _cil=$(find_cilium_pod "$_kc" "$_ctx") || { T_PEER_IPCACHE_NS=0; return 1; }
  while true; do
    _out=$(KUBECONFIG="$_kc" kubectl --context "$_ctx" -n kube-system exec "$_cil" -c cilium-agent -- \
      cilium-dbg bpf ipcache list 2>/dev/null || true)
    if [ -z "$_out" ]; then
      _out=$(KUBECONFIG="$_kc" kubectl --context "$_ctx" -n kube-system exec "$_cil" -c cilium-agent -- \
        cilium bpf ipcache list 2>/dev/null || true)
    fi
    if echo "$_out" | grep -qF "${_pod_ip}/32"; then
      T_PEER_IPCACHE_NS=$(date +%s%N); return 0
    fi
    _now=$(date +%s)
    if [ $((_now - _start)) -ge "$_deadline_s" ]; then
      T_PEER_IPCACHE_NS=0; return 1
    fi
    sleep 1
  done
}

# Wait for peer to see identity with the unique probe label. Sets T_PEER_IDENTITY_NS or 0.
wait_peer_identity() {
  local _kc="$1" _ctx="$2" _label_uuid="$3" _deadline_s="$4"
  local _start _now _cil _out
  _start=$(date +%s)
  _cil=$(find_cilium_pod "$_kc" "$_ctx") || { T_PEER_IDENTITY_NS=0; return 1; }
  while true; do
    _out=$(KUBECONFIG="$_kc" kubectl --context "$_ctx" -n kube-system exec "$_cil" -c cilium-agent -- \
      cilium identity list -o json 2>/dev/null || true)
    if [ -z "$_out" ]; then
      _out=$(KUBECONFIG="$_kc" kubectl --context "$_ctx" -n kube-system exec "$_cil" -c cilium-agent -- \
        cilium-dbg identity list -o json 2>/dev/null || true)
    fi
    if echo "$_out" | grep -qF "$_label_uuid"; then
      T_PEER_IDENTITY_NS=$(date +%s%N); return 0
    fi
    _now=$(date +%s)
    if [ $((_now - _start)) -ge "$_deadline_s" ]; then
      T_PEER_IDENTITY_NS=0; return 1
    fi
    sleep 1
  done
}

# Wait for peer-visible CiliumEndpoint for pod IP. Note: in some Cilium
# versions remote endpoints land as CiliumEndpointSlice entries rather than
# per-pod CEP CRDs — this may legitimately stay at 0 in AKS-managed Cilium.
# Sets T_PEER_CEP_NS or 0.
wait_peer_cep() {
  local _kc="$1" _ctx="$2" _pod_ip="$3" _deadline_s="$4"
  local _start _now
  _start=$(date +%s)
  while true; do
    if KUBECONFIG="$_kc" kubectl --context "$_ctx" get ciliumendpoints -A -o json 2>/dev/null | \
         grep -qF "$_pod_ip"; then
      T_PEER_CEP_NS=$(date +%s%N); return 0
    fi
    _now=$(date +%s)
    if [ $((_now - _start)) -ge "$_deadline_s" ]; then
      T_PEER_CEP_NS=0; return 1
    fi
    sleep 1
  done
}

# Connectivity probe via global Service DNS (NOT pod IP). Creates a Job-like
# client pod on the peer cluster that runs curl, waits for completion,
# reads logs, deletes pod (with --force --wait=false to keep it cheap).
# Outputs ConnectivityResults.jsonl row.
do_connectivity_probe() {
  local _peer_kc="$1" _peer_ctx="$2" _src_cluster="$3" _src_pod_hostname="$4"
  local _client_pod="probe-client-${PROBE_ID:0:8}-$(date +%s%N | tail -c 8)"
  local _t_attempt_ns
  _t_attempt_ns=$(date +%s%N)

  # Create curl client pod imperatively. Important: don't use --rm -i
  # (known to hang under load); poll Succeeded/Failed state.
  KUBECONFIG="$_peer_kc" kubectl --context "$_peer_ctx" -n "$PROBE_NS" run "$_client_pod" \
    --image="$CURL_IMAGE" --restart=Never --quiet --command -- \
    sh -c "curl -s -m 10 -o /tmp/body -w '%{http_code}|%{time_total}\n' http://${GLOBAL_SVC_DNS}/ && cat /tmp/body" \
    > /dev/null 2>&1 || true

  # Poll for completion: Succeeded or Failed, with 30s deadline.
  local _phase=""
  local _start
  _start=$(date +%s)
  while true; do
    _phase=$(KUBECONFIG="$_peer_kc" kubectl --context "$_peer_ctx" -n "$PROBE_NS" \
      get pod "$_client_pod" -o jsonpath='{.status.phase}' 2>/dev/null || echo "")
    case "$_phase" in
      Succeeded|Failed) break ;;
    esac
    local _now; _now=$(date +%s)
    if [ $((_now - _start)) -ge 30 ]; then break; fi
    sleep 0.5
  done

  local _logs _status _time _hostname _matches _matches_field
  _logs=$(KUBECONFIG="$_peer_kc" kubectl --context "$_peer_ctx" -n "$PROBE_NS" \
    logs "$_client_pod" 2>/dev/null || echo "")
  _status=$(echo "$_logs" | head -1 | cut -d'|' -f1 | tr -dc '0-9')
  _time=$(echo "$_logs" | head -1 | cut -d'|' -f2 | tr -dc '0-9.')
  _hostname=$(echo "$_logs" | tail -n +2 | tr -d '\n' | tr -dc 'a-zA-Z0-9_-' | head -c 100)
  # The global Service selector is `name: pp-backend-...` which matches
  # the workload's persistent backend Deployment, NOT our transient
  # probe pod. So the curl actually exercises global-service routing to
  # the workload backend (any cluster's backend Deployment is a valid
  # peer). returned_backend_pod_in_src tells us whether the curl was
  # served by a backend in the SOURCE cluster (which the global Service
  # is allowed to load-balance to either local OR remote). Combined with
  # peer_cluster, dashboards can compute fraction-served-from-remote
  # to validate the mesh-aware load balancing.
  #
  # NOTE: returned hostname pattern is the backend Deployment's pod name
  # (CL2-managed), not our unique probe pod hostname, so we can't directly
  # verify "did the curl reach OUR specific probe pod" — for that we'd
  # need a global Service that selects the probe label too (future work).
  _matches="false"
  [ -n "$_src_pod_hostname" ] && [ -n "$_hostname" ] && echo "$_hostname" | grep -qF "${_src_cluster}" && _matches="true"

  cat >> "$CONN_OUT" <<EOF
{"probe_id":"$PROBE_ID","src_cluster":"$_src_cluster","peer_cluster":"$_peer_ctx","global_service_dns":"$GLOBAL_SVC_DNS","t_curl_attempt_ns":$_t_attempt_ns,"curl_pod_phase":"$_phase","curl_http_status":"${_status:-0}","curl_total_seconds":"${_time:-0}","returned_hostname":"$_hostname","returned_backend_in_src":$_matches}
EOF

  # Cleanup peer-side client pod best-effort.
  KUBECONFIG="$_peer_kc" kubectl --context "$_peer_ctx" -n "$PROBE_NS" \
    delete pod "$_client_pod" --grace-period=0 --force --wait=false > /dev/null 2>&1 || true
}

# Per-peer worker: runs ipcache/identity/CEP waits in PARALLEL (each in
# its own sub-subshell writing its timestamp to a per-wait file) so the
# three "first-seen" times are independent — otherwise sequential waits
# bias the second/third timestamps to start only after the first one
# returns (e.g. identity time would appear ≈ ipcache time even if
# identity arrived first).
#
# Connectivity probe runs AFTER waits complete because it needs ipcache
# to be populated for the curl to succeed reliably.
# Wait for peer ipcache to REMOVE pod IP (poll until gone or timeout).
# Counterpart to wait_peer_ipcache — used by ENABLE_REMOVE_PROBE.
# Sets T_PEER_IPCACHE_REMOVED_NS or 0 on timeout.
wait_peer_ipcache_removed() {
  local _kc="$1" _ctx="$2" _pod_ip="$3" _deadline_s="$4"
  local _start _now _cil _out
  _start=$(date +%s)
  _cil=$(find_cilium_pod "$_kc" "$_ctx") || { T_PEER_IPCACHE_REMOVED_NS=0; return 1; }
  while true; do
    _out=$(KUBECONFIG="$_kc" kubectl --context "$_ctx" -n kube-system exec "$_cil" -c cilium-agent -- \
      cilium-dbg bpf ipcache list 2>/dev/null || true)
    if [ -z "$_out" ]; then
      _out=$(KUBECONFIG="$_kc" kubectl --context "$_ctx" -n kube-system exec "$_cil" -c cilium-agent -- \
        cilium bpf ipcache list 2>/dev/null || true)
    fi
    # IP NO LONGER present = success (removed)
    if ! echo "$_out" | grep -qF "${_pod_ip}/32"; then
      T_PEER_IPCACHE_REMOVED_NS=$(date +%s%N); return 0
    fi
    _now=$(date +%s)
    if [ $((_now - _start)) -ge "$_deadline_s" ]; then
      T_PEER_IPCACHE_REMOVED_NS=0; return 1
    fi
    sleep 1
  done
}

# Wait for peer identity GC after src pod delete. Polls cilium identity list
# until the unique LABEL_UUID is no longer present. Counterpart to
# wait_peer_identity (which waits for it to APPEAR). Sets
# T_PEER_IDENTITY_REMOVED_NS or 0 on timeout.
#
# NOTE: identity GC is RACE-prone — Cilium may keep the identity around
# briefly if other endpoints share the same label set, or may delay GC
# behind kvstoremesh sync intervals. Customers care about this because
# orphan identities consume kvstore keys + propagate via mesh.
wait_peer_identity_removed() {
  local _kc="$1" _ctx="$2" _label_uuid="$3" _deadline_s="$4"
  local _start _now _cil _out
  _start=$(date +%s)
  _cil=$(find_cilium_pod "$_kc" "$_ctx") || { T_PEER_IDENTITY_REMOVED_NS=0; return 1; }
  while true; do
    _out=$(KUBECONFIG="$_kc" kubectl --context "$_ctx" -n kube-system exec "$_cil" -c cilium-agent -- \
      cilium identity list -o json 2>/dev/null || true)
    if [ -z "$_out" ]; then
      _out=$(KUBECONFIG="$_kc" kubectl --context "$_ctx" -n kube-system exec "$_cil" -c cilium-agent -- \
        cilium-dbg identity list -o json 2>/dev/null || true)
    fi
    # Label UUID no longer present = identity GC'd
    if ! echo "$_out" | grep -qF "$_label_uuid"; then
      T_PEER_IDENTITY_REMOVED_NS=$(date +%s%N); return 0
    fi
    _now=$(date +%s)
    if [ $((_now - _start)) -ge "$_deadline_s" ]; then
      T_PEER_IDENTITY_REMOVED_NS=0; return 1
    fi
    sleep 1
  done
}

# Wait for peer to successfully curl the probe pod DIRECTLY by its IP
# (cross-cluster routing test). Records the first 200 OK from peer that
# returns the src probe pod's hostname (default nginx welcome page does
# NOT include hostname, so we use the /hostname endpoint via $hostname
# in default config — actually for cbl-mariner nginx the default page
# returns "Welcome to nginx!" — so we just match any 200 from THIS IP
# which proves cross-cluster routing reaches THIS specific pod).
# Sets T_PEER_FIRST_PACKET_NS = first 200 OK, or 0 on timeout.
#
# This is DIFFERENT from do_connectivity_probe which curls the global
# Service DNS (load-balanced across all backends). FIRST_PACKET measures
# direct cross-cluster routing to a specific new pod's IP.
wait_peer_first_packet() {
  local _kc="$1" _ctx="$2" _pod_ip="$3" _deadline_s="$4"
  T_PEER_FIRST_PACKET_NS=0
  if [ -z "$_pod_ip" ]; then return 1; fi
  local _client_pod="probe-fp-${PROBE_ID:0:8}-$(date +%s%N | tail -c 8)"
  KUBECONFIG="$_kc" kubectl --context "$_ctx" -n "$PROBE_NS" run "$_client_pod" \
    --image="$CURL_IMAGE" --restart=Never --quiet --command -- \
    sleep 3600 > /dev/null 2>&1 || true
  local _start; _start=$(date +%s)
  while true; do
    local _phase
    _phase=$(KUBECONFIG="$_kc" kubectl --context "$_ctx" -n "$PROBE_NS" \
      get pod "$_client_pod" -o jsonpath='{.status.phase}' 2>/dev/null || echo "")
    [ "$_phase" = "Running" ] && break
    local _now; _now=$(date +%s)
    [ $((_now - _start)) -ge 15 ] && break
    sleep 0.5
  done
  while true; do
    local _now; _now=$(date +%s)
    if [ $((_now - _start)) -ge "$_deadline_s" ]; then
      break
    fi
    local _status
    _status=$(KUBECONFIG="$_kc" kubectl --context "$_ctx" -n "$PROBE_NS" exec "$_client_pod" -- \
      curl -s -m 2 -o /dev/null -w '%{http_code}' "http://${_pod_ip}/" 2>/dev/null || echo "")
    if [ "$_status" = "200" ]; then
      T_PEER_FIRST_PACKET_NS=$(date +%s%N)
      break
    fi
    sleep 0.5
  done
  KUBECONFIG="$_kc" kubectl --context "$_ctx" -n "$PROBE_NS" \
    delete pod "$_client_pod" --grace-period=0 --force --wait=false > /dev/null 2>&1 || true
}

# Wait for peer's BPF lb map to include pod_ip as a backend of any Service.
# Customer answer: "when does the new pod start receiving cross-cluster
# Service traffic?" Requires a global Service that selects the probe pod
# (created by create_probe_service below when ENABLE_SERVICE_BACKEND_PROBE
# is true). Sets T_PEER_SERVICE_BACKEND_NS or 0 on timeout.
#
# cilium-dbg bpf lb list output format:
#   SERVICE ADDRESS    BACKEND ADDRESS (REVNAT_ID) (SLOT)
#   10.0.0.42:80       10.1.4.123:80  (1) (1)
#                      10.2.4.45:80   (1) (2)
# We just grep for the pod IP appearing anywhere in the output.
wait_peer_service_backend() {
  local _kc="$1" _ctx="$2" _pod_ip="$3" _deadline_s="$4"
  T_PEER_SERVICE_BACKEND_NS=0
  local _start _now _cil _out
  _start=$(date +%s)
  _cil=$(find_cilium_pod "$_kc" "$_ctx") || return 1
  while true; do
    _out=$(KUBECONFIG="$_kc" kubectl --context "$_ctx" -n kube-system exec "$_cil" -c cilium-agent -- \
      cilium-dbg bpf lb list 2>/dev/null || true)
    if [ -z "$_out" ]; then
      _out=$(KUBECONFIG="$_kc" kubectl --context "$_ctx" -n kube-system exec "$_cil" -c cilium-agent -- \
        cilium bpf lb list 2>/dev/null || true)
    fi
    if echo "$_out" | grep -qF "${_pod_ip}:"; then
      T_PEER_SERVICE_BACKEND_NS=$(date +%s%N); return 0
    fi
    _now=$(date +%s)
    if [ $((_now - _start)) -ge "$_deadline_s" ]; then
      return 1
    fi
    sleep 1
  done
}

# Create a transient global Service on the SOURCE cluster that selects
# exactly the probe pod via its unique propagation-probe-id label. This
# Service gets global annotation so clustermesh-apiserver propagates it
# to ALL peers. Once a peer's cilium-agent sees the Service + backend,
# the pod IP appears in `cilium-dbg bpf lb list`. That's what
# wait_peer_service_backend polls for.
create_probe_service() {
  local _kc="$1" _ctx="$2" _label_uuid="$3" _svc_name="$4"
  cat <<EOF | KUBECONFIG="$_kc" kubectl --context "$_ctx" -n "$PROBE_NS" apply -f - > /dev/null 2>&1
apiVersion: v1
kind: Service
metadata:
  name: ${_svc_name}
  annotations:
    service.cilium.io/global: "true"
    io.cilium/global-service: "true"
spec:
  selector:
    propagation-probe-id: "${_label_uuid}"
  ports:
    - name: http
      port: 80
      targetPort: 80
      protocol: TCP
EOF
}

delete_probe_service() {
  local _kc="$1" _ctx="$2" _svc_name="$3"
  KUBECONFIG="$_kc" kubectl --context "$_ctx" -n "$PROBE_NS" \
    delete svc "$_svc_name" --ignore-not-found --wait=false > /dev/null 2>&1 || true
}

# Per-cluster remove-probe orchestration. Runs only if ENABLE_REMOVE_PROBE=true.
# Run AFTER peer_probe finishes (we need to know the IP propagated first;
# remove timing is most useful as delta from t_delete on src).
peer_remove_probe() {
  local _kc="$1" _ctx="$2" _pod_ip="$3" _outfile="$4" _t_delete_ns="$5" _src_cluster="$6" _label_uuid="${7:-}"
  T_PEER_IPCACHE_REMOVED_NS=0
  T_PEER_IDENTITY_REMOVED_NS=0
  # Run ipcache + identity GC waits in PARALLEL — they're independent
  # measurements (identity GC may complete before/after ipcache cleanup).
  local _peerdir
  _peerdir=$(mktemp -d)
  (
    wait_peer_ipcache_removed "$_kc" "$_ctx" "$_pod_ip" "$REMOVE_PROBE_TIMEOUT_S" || true
    echo "$T_PEER_IPCACHE_REMOVED_NS" > "$_peerdir/ipcache_removed"
  ) &
  if [ -n "$_label_uuid" ]; then
    (
      wait_peer_identity_removed "$_kc" "$_ctx" "$_label_uuid" "$REMOVE_PROBE_TIMEOUT_S" || true
      echo "$T_PEER_IDENTITY_REMOVED_NS" > "$_peerdir/identity_removed"
    ) &
  fi
  wait
  T_PEER_IPCACHE_REMOVED_NS=$(cat "$_peerdir/ipcache_removed" 2>/dev/null || echo 0)
  T_PEER_IDENTITY_REMOVED_NS=$(cat "$_peerdir/identity_removed" 2>/dev/null || echo 0)
  rm -rf "$_peerdir"
  local _delta_ms _delta_id_ms _timed_out
  if [ "$T_PEER_IPCACHE_REMOVED_NS" -eq 0 ]; then
    _delta_ms="null"
    _timed_out=true
  else
    _delta_ms=$(( (T_PEER_IPCACHE_REMOVED_NS - _t_delete_ns) / 1000000 ))
    _timed_out=false
  fi
  if [ "$T_PEER_IDENTITY_REMOVED_NS" -eq 0 ]; then
    _delta_id_ms="null"
  else
    _delta_id_ms=$(( (T_PEER_IDENTITY_REMOVED_NS - _t_delete_ns) / 1000000 ))
  fi
  cat > "$_outfile" <<EOF
{"probe_id":"$PROBE_ID","src_cluster":"$_src_cluster","peer_cluster":"$_ctx","pod_ip":"$_pod_ip","label_uuid":"$_label_uuid","t_delete_ns":$_t_delete_ns,"t_peer_ipcache_removed_ns":$T_PEER_IPCACHE_REMOVED_NS,"delta_remove_ms":$_delta_ms,"t_peer_identity_removed_ns":$T_PEER_IDENTITY_REMOVED_NS,"delta_identity_gc_ms":$_delta_id_ms,"peer_remove_timed_out":$_timed_out}
EOF
}

peer_probe() {
  local _kc="$1" _ctx="$2" _pod_ip="$3" _label_uuid="$4" _src_cluster="$5" _src_pod_hostname="$6" _outfile="$7"
  T_PEER_IPCACHE_NS=0
  T_PEER_IDENTITY_NS=0
  T_PEER_CEP_NS=0
  T_PEER_FIRST_PACKET_NS=0
  local _peerdir
  _peerdir=$(mktemp -d)
  (
    wait_peer_ipcache "$_kc" "$_ctx" "$_pod_ip" "$PEER_TIMEOUT_S" || true
    echo "$T_PEER_IPCACHE_NS" > "$_peerdir/ipcache"
  ) &
  (
    wait_peer_identity "$_kc" "$_ctx" "$_label_uuid" "$PEER_TIMEOUT_S" || true
    echo "$T_PEER_IDENTITY_NS" > "$_peerdir/identity"
  ) &
  (
    wait_peer_cep "$_kc" "$_ctx" "$_pod_ip" "$PEER_TIMEOUT_S" || true
    echo "$T_PEER_CEP_NS" > "$_peerdir/cep"
  ) &
  # First-packet probe runs in parallel — starts tight-loop curling
  # the probe pod's IP DIRECTLY (not the global Service). Records first
  # 200 OK = cross-cluster routing actually reaches THIS specific new
  # pod. Requires the probe pod to be running nginx (auto-selected when
  # ENABLE_FIRST_PACKET_PROBE=true, see container spec above).
  if [ "$ENABLE_FIRST_PACKET_PROBE" = "true" ]; then
    (
      wait_peer_first_packet "$_kc" "$_ctx" "$_pod_ip" "$FIRST_PACKET_PROBE_TIMEOUT_S" || true
      echo "$T_PEER_FIRST_PACKET_NS" > "$_peerdir/first_packet"
    ) &
  fi
  # Service-backend membership: when does peer's BPF lb map include the
  # new pod as a backend of the transient global Service? Requires
  # ENABLE_SERVICE_BACKEND_PROBE=true (which creates the transient Service
  # on the source cluster before peer_probe is called).
  if [ "$ENABLE_SERVICE_BACKEND_PROBE" = "true" ]; then
    (
      wait_peer_service_backend "$_kc" "$_ctx" "$_pod_ip" "$SERVICE_BACKEND_PROBE_TIMEOUT_S" || true
      echo "$T_PEER_SERVICE_BACKEND_NS" > "$_peerdir/service_backend"
    ) &
  fi
  wait
  T_PEER_IPCACHE_NS=$(cat "$_peerdir/ipcache" 2>/dev/null || echo 0)
  T_PEER_IDENTITY_NS=$(cat "$_peerdir/identity" 2>/dev/null || echo 0)
  T_PEER_CEP_NS=$(cat "$_peerdir/cep" 2>/dev/null || echo 0)
  T_PEER_FIRST_PACKET_NS=$(cat "$_peerdir/first_packet" 2>/dev/null || echo 0)
  T_PEER_SERVICE_BACKEND_NS=$(cat "$_peerdir/service_backend" 2>/dev/null || echo 0)
  rm -rf "$_peerdir"
  local _timed_out
  _timed_out=$([ "$T_PEER_IPCACHE_NS" -eq 0 ] && echo true || echo false)
  local _delta_fp_ms="null"
  if [ "$T_PEER_FIRST_PACKET_NS" -ne 0 ] && [ "$T_POD_READY_NS" -ne 0 ]; then
    _delta_fp_ms=$(( (T_PEER_FIRST_PACKET_NS - T_POD_READY_NS) / 1000000 ))
  fi
  local _delta_sb_ms="null"
  if [ "$T_PEER_SERVICE_BACKEND_NS" -ne 0 ] && [ "$T_POD_READY_NS" -ne 0 ]; then
    _delta_sb_ms=$(( (T_PEER_SERVICE_BACKEND_NS - T_POD_READY_NS) / 1000000 ))
  fi
  cat > "$_outfile" <<EOF
{"probe_id":"$PROBE_ID","probe_ns":"$PROBE_NS","src_cluster":"$_src_cluster","peer_cluster":"$_ctx","label_uuid":"$_label_uuid","pod_ip":"$_pod_ip","pod_hostname":"$_src_pod_hostname","t_apply_ns":$T_APPLY_NS,"t_scheduled_ns":$T_SCHEDULED_NS,"t_ip_assigned_ns":$T_IP_ASSIGNED_NS,"t_pod_ready_ns":$T_POD_READY_NS,"t_local_ep_ns":$T_LOCAL_EP_NS,"t_peer_ipcache_ns":$T_PEER_IPCACHE_NS,"t_peer_identity_ns":$T_PEER_IDENTITY_NS,"t_peer_cep_ns":$T_PEER_CEP_NS,"t_peer_first_packet_ns":$T_PEER_FIRST_PACKET_NS,"delta_first_packet_ms":$_delta_fp_ms,"t_peer_service_backend_ns":$T_PEER_SERVICE_BACKEND_NS,"delta_service_backend_ms":$_delta_sb_ms,"peer_timed_out":$_timed_out}
EOF
  if [ "$ENABLE_CONNECTIVITY" = "true" ] && [ "$T_PEER_IPCACHE_NS" -ne 0 ] && [ -n "$GLOBAL_SVC_DNS" ]; then
    do_connectivity_probe "$_kc" "$_ctx" "$_src_cluster" "$_src_pod_hostname"
  fi
}

# Cleanup-on-exit handler for any in-flight probe pods. Best-effort across
# all clusters (script may be killed mid-iteration).
cleanup_probe_pods() {
  for i in $(seq 0 $((CLUSTER_COUNT - 1))); do
    local _kc _ctx
    _kc=$(jq -r ".[$i].kubeconfig" < "$CLUSTERS_JSON")
    _ctx=$(jq -r ".[$i].name" < "$CLUSTERS_JSON")
    KUBECONFIG="$_kc" kubectl --context "$_ctx" -n "$PROBE_NS" \
      delete pod -l app=propagation-probe --grace-period=0 --force --wait=false > /dev/null 2>&1 || true
  done
}
trap cleanup_probe_pods EXIT

# Now run preflight (function defined above). All function definitions
# need to be in scope before we invoke them — preflight calls
# find_cilium_pod which is defined just above this trap. Same for
# discover_global_svc_dns.
if ! preflight_cilium_commands; then
  echo "[probe] aborting due to preflight failure — emit empty PropagationTimings.jsonl so collect.py sees zero rows (rather than missing file)" >&2
  : > "$PROP_OUT"
  exit 1
fi
# Resolve the global Service DNS at startup (if connectivity enabled).
# If discovery fails we proceed with propagation-only mode.
if [ "$ENABLE_CONNECTIVITY" = "true" ]; then
  discover_global_svc_dns
fi

for p in $(seq 1 "$PROBE_COUNT"); do
  PROBE_ID=$(uuidgen 2>/dev/null || cat /proc/sys/kernel/random/uuid)
  SRC_IDX=$((RANDOM % CLUSTER_COUNT))
  SRC_NAME=$(jq -r ".[$SRC_IDX].name" < "$CLUSTERS_JSON")
  SRC_KC=$(jq -r ".[$SRC_IDX].kubeconfig" < "$CLUSTERS_JSON")
  POD_NAME="probe-${PROBE_ID:0:8}"
  LABEL_UUID="$PROBE_ID"
  POD_HOSTNAME="probe-${SRC_NAME}-${LABEL_UUID:0:8}"

  echo "[probe $p/$PROBE_COUNT] src=$SRC_NAME id=$PROBE_ID pod=$POD_NAME"

  T_APPLY_NS=$(date +%s%N)
  # Choose container spec: pause (default, cheap, no HTTP) OR nginx (when
  # FIRST_PACKET probe is enabled — needs HTTP server to curl against).
  if [ "$ENABLE_FIRST_PACKET_PROBE" = "true" ]; then
    PROBE_POD_CONTAINER=$(cat <<EOF
  - name: probe-http
    image: $PROBE_HTTP_IMAGE
    # cbl-mariner nginx has no ENTRYPOINT — must set explicit command.
    command: ["nginx", "-g", "daemon off;"]
    readinessProbe:
      tcpSocket:
        port: 80
      initialDelaySeconds: 1
      periodSeconds: 1
EOF
    )
  else
    PROBE_POD_CONTAINER=$(cat <<EOF
  - name: pause
    image: $PROBE_IMAGE
EOF
    )
  fi
  cat <<EOF | KUBECONFIG="$SRC_KC" kubectl --context "$SRC_NAME" -n "$PROBE_NS" apply -f - > /dev/null 2>&1
apiVersion: v1
kind: Pod
metadata:
  name: $POD_NAME
  labels:
    propagation-probe-id: "$LABEL_UUID"
    propagation-probe-src: "$SRC_NAME"
    app: propagation-probe
spec:
  hostname: $POD_HOSTNAME
  containers:
$PROBE_POD_CONTAINER
  restartPolicy: Never
EOF

  if ! wait_pod_ip "$SRC_KC" "$SRC_NAME" "$PROBE_NS" "$POD_NAME" 60; then
    echo "[probe $p] FAIL: pod $POD_NAME never got an IP within 60s"
    continue
  fi
  T_IP_ASSIGNED_NS=$(date +%s%N)

  SCHEDULED_ISO=$(KUBECONFIG="$SRC_KC" kubectl --context "$SRC_NAME" -n "$PROBE_NS" \
    get pod "$POD_NAME" -o jsonpath='{.status.conditions[?(@.type=="PodScheduled")].lastTransitionTime}' 2>/dev/null)
  T_SCHEDULED_NS=$T_APPLY_NS
  if [ -n "$SCHEDULED_ISO" ]; then
    T_SCHEDULED_NS=$(date -d "$SCHEDULED_ISO" +%s%N 2>/dev/null || echo "$T_APPLY_NS")
  fi

  wait_pod_ready "$SRC_KC" "$SRC_NAME" "$PROBE_NS" "$POD_NAME" 60 || true
  wait_local_endpoint "$SRC_KC" "$SRC_NAME" "$POD_IP" 30 || true

  # Service-backend probe: create a transient global Service that selects
  # exactly THIS probe pod (via propagation-probe-id label). The Service
  # propagates via clustermesh-apiserver to all peers; peers' cilium-agent
  # adds the pod IP to their BPF lb map. wait_peer_service_backend polls
  # for that. Measures "how long until a new global Service's backend is
  # load-balanceable from every peer?" — the gap #3 customer question.
  PROBE_SVC_NAME=""
  if [ "$ENABLE_SERVICE_BACKEND_PROBE" = "true" ]; then
    PROBE_SVC_NAME="probe-svc-${LABEL_UUID:0:8}"
    create_probe_service "$SRC_KC" "$SRC_NAME" "$LABEL_UUID" "$PROBE_SVC_NAME"
    echo "[probe $p] created transient global Service $PROBE_SVC_NAME (selector: propagation-probe-id=$LABEL_UUID)"
  fi

  # Choose peers. Cap at PEER_SAMPLE_MAX, exclude source.
  PEER_IDXS=""
  for i in $(seq 0 $((CLUSTER_COUNT - 1))); do
    [ "$i" -eq "$SRC_IDX" ] && continue
    PEER_IDXS="$PEER_IDXS $i"
  done
  PEER_COUNT_RAW=$(echo "$PEER_IDXS" | wc -w)
  if [ "$PEER_COUNT_RAW" -gt "$PEER_SAMPLE_MAX" ]; then
    PEER_IDXS=$(echo $PEER_IDXS | tr ' ' '\n' | shuf | head -n "$PEER_SAMPLE_MAX" | tr '\n' ' ')
  fi

  TMPDIR=$(mktemp -d)
  for pi in $PEER_IDXS; do
    PEER_NAME=$(jq -r ".[$pi].name" < "$CLUSTERS_JSON")
    PEER_KC=$(jq -r ".[$pi].kubeconfig" < "$CLUSTERS_JSON")
    peer_probe "$PEER_KC" "$PEER_NAME" "$POD_IP" "$LABEL_UUID" "$SRC_NAME" "$POD_HOSTNAME" "$TMPDIR/$pi.json" &
  done
  wait
  cat "$TMPDIR"/*.json >> "$PROP_OUT" 2>/dev/null
  rm -rf "$TMPDIR"

  # Delete probe pod on src. If ENABLE_REMOVE_PROBE, capture t_delete
  # and PARALLEL poll peers for ipcache REMOVAL (stale-state risk metric).
  T_DELETE_NS=$(date +%s%N)
  KUBECONFIG="$SRC_KC" kubectl --context "$SRC_NAME" -n "$PROBE_NS" \
    delete pod "$POD_NAME" --grace-period=0 --force --wait=false > /dev/null 2>&1 || true

  if [ "$ENABLE_REMOVE_PROBE" = "true" ]; then
    RMDIR=$(mktemp -d)
    for pi in $PEER_IDXS; do
      PEER_NAME=$(jq -r ".[$pi].name" < "$CLUSTERS_JSON")
      PEER_KC=$(jq -r ".[$pi].kubeconfig" < "$CLUSTERS_JSON")
      peer_remove_probe "$PEER_KC" "$PEER_NAME" "$POD_IP" "$RMDIR/$pi.json" "$T_DELETE_NS" "$SRC_NAME" "$LABEL_UUID" &
    done
    wait
    cat "$RMDIR"/*.json >> "$REMOVE_OUT" 2>/dev/null
    rm -rf "$RMDIR"
  fi

  # Delete the transient probe Service (if created) AFTER remove-probe
  # so the Service-backend removal propagation is also measured by
  # peer_remove_probe's ipcache-removal timer (the pod is gone → the
  # Service eventually has 0 backends → peers drop it from lb map).
  if [ -n "$PROBE_SVC_NAME" ]; then
    delete_probe_service "$SRC_KC" "$SRC_NAME" "$PROBE_SVC_NAME"
  fi

  if [ "$p" -lt "$PROBE_COUNT" ]; then
    sleep "$PROBE_INTERVAL_S"
  fi
done

echo "[probe] complete. PropagationTimings.jsonl: $(wc -l < "$PROP_OUT") rows"
[ "$ENABLE_CONNECTIVITY" = "true" ] && \
  echo "[probe] ConnectivityResults.jsonl: $(wc -l < "$CONN_OUT") rows"
[ "$ENABLE_REMOVE_PROBE" = "true" ] && \
  echo "[probe] RemovePropagationTimings.jsonl: $(wc -l < "$REMOVE_OUT") rows"
exit 0
