#!/bin/bash
# mesh-recovery-probe.sh
#
# Host-side mesh-state recovery probe orchestrator. Like propagation-probe.sh
# but measures RECOVERY (not initial propagation): kills the cilium-agent pod
# on one cluster, then measures how long until peer ipcache + identity state
# converges back to the pre-kill view.
#
# Why this exists: AKS node upgrades, agent OOMKills, config-driven restarts
# all destroy and rebuild the cilium agent on a node. Customers want to know
# "after my Cilium agent restarts, how long until my mesh is healthy again."
# This probe measures that directly.
#
# Pattern mirrors propagation-probe.sh: invoked by execute.yml's
# launch_mesh_recovery_probe (background subshell), runs while CL2 sleeps
# in a controlled window, writes ResilienceTimings.jsonl that scale.py
# collect uploads to Kusto as ClusterMeshRecoveryProbe rows.
#
# Per probe iteration:
#   1. Pick a random TARGET cluster from the mesh. Pick its cilium-agent pod
#      on its first node.
#   2. Pick a SAMPLE peer cluster (different from target).
#   3. Snapshot pre-kill state on the sample peer: capture ipcache lines
#      containing pod IPs that are SOURCED FROM the target cluster (we use
#      a known label/identity marker from the pp-backend deployment).
#   4. T_KILL_NS: delete the target's cilium-agent pod (kubectl delete --grace-period=0).
#   5. Poll the sample peer's ipcache for the snapshot entries:
#      - T_GONE_NS = first moment ANY pre-kill entry disappears from peer ipcache
#        (kvstore lease expiration after kill propagates)
#      - Wait for target's new cilium-agent pod to come up (Running+Ready).
#      - T_AGENT_READY_NS = new pod Ready.
#      - T_RESYNCED_NS = first moment ALL pre-kill entries are back in
#        peer's ipcache (full re-sync from new agent).
#   6. Emit ResilienceTimings.jsonl row:
#      {probe_id, target_cluster, target_pod, sample_peer, snapshot_count,
#       t_kill_ns, t_gone_ns, t_agent_ready_ns, t_resynced_ns,
#       delta_to_gone_ms, delta_to_agent_ready_ms, delta_to_resynced_ms,
#       timed_out}
#   7. Sleep PROBE_INTERVAL_S before next iteration.
#
# Args (positional):
#   $1  PROBE_COUNT            number of kill+recover cycles (e.g. 5)
#   $2  PROBE_INTERVAL_S       seconds between iterations (default 120)
#   $3  PROBE_NS               namespace where workload backends live
#                              (clustermesh-probe-1)
#   $4  RECOVERY_TIMEOUT_S     per-iteration wait deadline (default 300)
#   $5  CLUSTERS_JSON          path to augmented clusters JSON
#   $6  OUTPUT_DIR             dir for JSONL output
#
# Output: ResilienceTimings.jsonl, one row per kill+recovery iteration.

set -uo pipefail

PROBE_COUNT="${1:?PROBE_COUNT required}"
PROBE_INTERVAL_S="${2:?PROBE_INTERVAL_S required}"
PROBE_NS="${3:?PROBE_NS required}"
RECOVERY_TIMEOUT_S="${4:?RECOVERY_TIMEOUT_S required}"
CLUSTERS_JSON="${5:?CLUSTERS_JSON required}"
OUTPUT_DIR="${6:?OUTPUT_DIR required}"

OUT="${OUTPUT_DIR}/ResilienceTimings.jsonl"
mkdir -p "$OUTPUT_DIR"
: > "$OUT"

if [ ! -f "$CLUSTERS_JSON" ]; then
  echo "FATAL: CLUSTERS_JSON $CLUSTERS_JSON not found" >&2
  exit 1
fi

CLUSTER_COUNT=$(jq 'length' < "$CLUSTERS_JSON")
if [ "$CLUSTER_COUNT" -lt 2 ]; then
  echo "FATAL: need >=2 clusters, found $CLUSTER_COUNT" >&2
  exit 1
fi

echo "[recovery] start: count=$PROBE_COUNT interval=${PROBE_INTERVAL_S}s ns=$PROBE_NS recovery_timeout=${RECOVERY_TIMEOUT_S}s clusters=$CLUSTER_COUNT"

# Find cilium-agent pod on a specific node (or any node if _node empty).
find_cilium_pod() {
  local _kc="$1" _ctx="$2" _node="$3"
  for sel in 'k8s-app=cilium' 'app.kubernetes.io/name=cilium' 'name=cilium'; do
    local _pod
    if [ -n "$_node" ]; then
      _pod=$(KUBECONFIG="$_kc" kubectl --context "$_ctx" -n kube-system get pod \
        -l "$sel" --field-selector "spec.nodeName=$_node" \
        -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
    else
      _pod=$(KUBECONFIG="$_kc" kubectl --context "$_ctx" -n kube-system get pod \
        -l "$sel" -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
    fi
    if [ -n "$_pod" ]; then echo "$_pod"; return 0; fi
  done
  return 1
}

# Get cilium-agent pod UID — used to detect that the pod was actually
# REPLACED (not just rescheduled with same name).
get_pod_uid() {
  local _kc="$1" _ctx="$2" _pod="$3"
  KUBECONFIG="$_kc" kubectl --context "$_ctx" -n kube-system get pod "$_pod" \
    -o jsonpath='{.metadata.uid}' 2>/dev/null || echo ""
}

# Get the IPs of backend pods (group=clustermesh-propagation-probe) on
# a cluster. Stable across the run (vs propagation probe's transient
# probe pods which churn). Returns space-separated list.
get_backend_pod_ips() {
  local _kc="$1" _ctx="$2"
  KUBECONFIG="$_kc" kubectl --context "$_ctx" -n "$PROBE_NS" get pod \
    -l group=clustermesh-propagation-probe \
    -o jsonpath='{range .items[*]}{.status.podIP}{" "}{end}' 2>/dev/null || echo ""
}

# Get the FIRST backend pod's nodeName on a cluster — we'll kill the
# cilium-agent on THAT node so the kill has a measurable effect on
# the backend endpoint state we just snapshotted.
get_backend_first_node() {
  local _kc="$1" _ctx="$2"
  KUBECONFIG="$_kc" kubectl --context "$_ctx" -n "$PROBE_NS" get pod \
    -l group=clustermesh-propagation-probe \
    -o jsonpath='{.items[0].spec.nodeName}' 2>/dev/null || echo ""
}

# Snapshot peer ipcache entries for the EXACT backend IPs (not broad CIDR).
# Records each IP that's present in peer ipcache. Returns space-separated list.
snapshot_peer_backend_ipcache() {
  local _peer_kc="$1" _peer_ctx="$2" _target_ips="$3"
  local _cil _all _present=""
  _cil=$(find_cilium_pod "$_peer_kc" "$_peer_ctx" "")
  [ -z "$_cil" ] && { echo ""; return 1; }
  _all=$(KUBECONFIG="$_peer_kc" kubectl --context "$_peer_ctx" -n kube-system exec "$_cil" -c cilium-agent -- \
    cilium-dbg bpf ipcache list 2>/dev/null || true)
  [ -z "$_all" ] && _all=$(KUBECONFIG="$_peer_kc" kubectl --context "$_peer_ctx" -n kube-system exec "$_cil" -c cilium-agent -- \
    cilium bpf ipcache list 2>/dev/null || true)
  for ip in $_target_ips; do
    [ -z "$ip" ] && continue
    if echo "$_all" | grep -qF "${ip}/32"; then
      _present="$_present $ip"
    fi
  done
  echo "$_present" | xargs
}

# Count how many of the snapshot IPs are currently present in peer ipcache.
count_snapshot_present() {
  local _peer_kc="$1" _peer_ctx="$2" _snap_ips="$3"
  local _cil _all _count=0
  _cil=$(find_cilium_pod "$_peer_kc" "$_peer_ctx" "")
  [ -z "$_cil" ] && { echo "-1"; return 1; }
  _all=$(KUBECONFIG="$_peer_kc" kubectl --context "$_peer_ctx" -n kube-system exec "$_cil" -c cilium-agent -- \
    cilium-dbg bpf ipcache list 2>/dev/null || true)
  [ -z "$_all" ] && _all=$(KUBECONFIG="$_peer_kc" kubectl --context "$_peer_ctx" -n kube-system exec "$_cil" -c cilium-agent -- \
    cilium bpf ipcache list 2>/dev/null || true)
  for ip in $_snap_ips; do
    [ -z "$ip" ] && continue
    echo "$_all" | grep -qF "${ip}/32" && _count=$((_count + 1))
  done
  echo "$_count"
}

# Cleanup-on-exit: best-effort
trap 'echo "[recovery] cleanup on exit"' EXIT

for p in $(seq 1 "$PROBE_COUNT"); do
  PROBE_ID=$(uuidgen 2>/dev/null || cat /proc/sys/kernel/random/uuid)
  # Pick TARGET cluster randomly.
  TGT_IDX=$((RANDOM % CLUSTER_COUNT))
  TGT_NAME=$(jq -r ".[$TGT_IDX].name" < "$CLUSTERS_JSON")
  TGT_KC=$(jq -r ".[$TGT_IDX].kubeconfig" < "$CLUSTERS_JSON")
  # Pick PEER cluster — any other.
  PEER_IDX=$(( (TGT_IDX + 1) % CLUSTER_COUNT ))
  PEER_NAME=$(jq -r ".[$PEER_IDX].name" < "$CLUSTERS_JSON")
  PEER_KC=$(jq -r ".[$PEER_IDX].kubeconfig" < "$CLUSTERS_JSON")

  # Get the EXACT backend pod IPs on target cluster (stable across run).
  TGT_BACKEND_IPS=$(get_backend_pod_ips "$TGT_KC" "$TGT_NAME")
  TGT_BACKEND_NODE=$(get_backend_first_node "$TGT_KC" "$TGT_NAME")
  if [ -z "$TGT_BACKEND_IPS" ] || [ -z "$TGT_BACKEND_NODE" ]; then
    echo "[recovery $p/$PROBE_COUNT] target=$TGT_NAME has no backend pods in $PROBE_NS; skipping (recovery probe needs propagation-probe backends to be up)"
    continue
  fi

  # Snapshot peer's ipcache for those exact backend IPs (not a coarse CIDR).
  SNAP_PRESENT=$(snapshot_peer_backend_ipcache "$PEER_KC" "$PEER_NAME" "$TGT_BACKEND_IPS")
  SNAP_COUNT=$(echo "$SNAP_PRESENT" | wc -w)
  if [ "$SNAP_COUNT" -eq 0 ]; then
    echo "[recovery $p/$PROBE_COUNT] target=$TGT_NAME backend IPs ($TGT_BACKEND_IPS) NOT visible in peer $PEER_NAME ipcache yet (mesh not converged?); skipping iteration"
    cat >> "$OUT" <<EOF
{"probe_id":"$PROBE_ID","target_cluster":"$TGT_NAME","sample_peer":"$PEER_NAME","snapshot_count":0,"error":"backend_ips_not_in_peer_ipcache","target_backend_ips":"$TGT_BACKEND_IPS"}
EOF
    if [ "$p" -lt "$PROBE_COUNT" ]; then sleep "$PROBE_INTERVAL_S"; fi
    continue
  fi

  # Kill the cilium-agent on the SAME node that hosts a backend pod —
  # otherwise the kill won't affect the snapshotted endpoint state.
  TGT_POD=$(find_cilium_pod "$TGT_KC" "$TGT_NAME" "$TGT_BACKEND_NODE")
  if [ -z "$TGT_POD" ]; then
    echo "[recovery $p/$PROBE_COUNT] no cilium-agent on node $TGT_BACKEND_NODE; skipping"
    continue
  fi
  TGT_UID_PRE=$(get_pod_uid "$TGT_KC" "$TGT_NAME" "$TGT_POD")

  echo "[recovery $p/$PROBE_COUNT] target=$TGT_NAME node=$TGT_BACKEND_NODE cilium=$TGT_POD (uid=${TGT_UID_PRE:0:8}) peer=$PEER_NAME backend_ips=$SNAP_PRESENT (count=$SNAP_COUNT)"

  T_KILL_NS=$(date +%s%N)
  KUBECONFIG="$TGT_KC" kubectl --context "$TGT_NAME" -n kube-system \
    delete pod "$TGT_POD" --grace-period=0 --force --wait=false > /dev/null 2>&1 || \
    echo "[recovery $p] kill reported error (continuing)"

  # 3) Poll for ipcache divergence + agent recovery + ipcache resync.
  T_GONE_NS=0
  T_AGENT_READY_NS=0
  T_RESYNCED_NS=0
  _start=$(date +%s)
  while true; do
    _now=$(date +%s)
    _elapsed=$((_now - _start))
    if [ "$_elapsed" -ge "$RECOVERY_TIMEOUT_S" ]; then
      echo "[recovery $p] timeout at ${_elapsed}s; recording partial state"
      break
    fi

    # Check for new agent pod (different UID) on the SAME node.
    if [ "$T_AGENT_READY_NS" -eq 0 ]; then
      _new_pod=$(find_cilium_pod "$TGT_KC" "$TGT_NAME" "$TGT_BACKEND_NODE")
      if [ -n "$_new_pod" ]; then
        _new_uid=$(get_pod_uid "$TGT_KC" "$TGT_NAME" "$_new_pod")
        if [ -n "$_new_uid" ] && [ "$_new_uid" != "$TGT_UID_PRE" ]; then
          _ready=$(KUBECONFIG="$TGT_KC" kubectl --context "$TGT_NAME" -n kube-system \
            get pod "$_new_pod" -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}' 2>/dev/null || echo "")
          if [ "$_ready" = "True" ]; then
            T_AGENT_READY_NS=$(date +%s%N)
            echo "[recovery $p] agent replaced + Ready (new pod=$_new_pod) after ${_elapsed}s"
          fi
        fi
      fi
    fi

    # Check peer ipcache state for our snapshotted IPs.
    _present=$(count_snapshot_present "$PEER_KC" "$PEER_NAME" "$SNAP_PRESENT")
    if [ "$T_GONE_NS" -eq 0 ] && [ "$_present" -lt "$SNAP_COUNT" ] && [ "$_present" != "-1" ]; then
      T_GONE_NS=$(date +%s%N)
      echo "[recovery $p] peer ipcache divergence: $_present / $SNAP_COUNT entries (after ${_elapsed}s)"
    fi
    if [ "$T_RESYNCED_NS" -eq 0 ] && [ "$T_AGENT_READY_NS" -ne 0 ] && [ "$_present" -ge "$SNAP_COUNT" ]; then
      T_RESYNCED_NS=$(date +%s%N)
      echo "[recovery $p] peer ipcache resynced: $_present / $SNAP_COUNT entries (after ${_elapsed}s)"
      break
    fi
    sleep 2
  done

  # Compute deltas (ms; 0 if not measured).
  _calc_delta_ms() {
    local _start_ns="$1" _end_ns="$2"
    if [ "$_end_ns" -eq 0 ] || [ "$_start_ns" -eq 0 ]; then echo 0; return; fi
    echo $(( (_end_ns - _start_ns) / 1000000 ))
  }
  DELTA_GONE_MS=$(_calc_delta_ms "$T_KILL_NS" "$T_GONE_NS")
  DELTA_AGENT_MS=$(_calc_delta_ms "$T_KILL_NS" "$T_AGENT_READY_NS")
  DELTA_RESYNC_MS=$(_calc_delta_ms "$T_KILL_NS" "$T_RESYNCED_NS")
  TIMED_OUT=$([ "$T_RESYNCED_NS" -eq 0 ] && echo "true" || echo "false")

  cat >> "$OUT" <<EOF
{"probe_id":"$PROBE_ID","target_cluster":"$TGT_NAME","target_node":"$TGT_BACKEND_NODE","target_pod":"$TGT_POD","target_uid_pre":"$TGT_UID_PRE","sample_peer":"$PEER_NAME","snapshot_ips":"$SNAP_PRESENT","snapshot_count":$SNAP_COUNT,"t_kill_ns":$T_KILL_NS,"t_gone_ns":$T_GONE_NS,"t_agent_ready_ns":$T_AGENT_READY_NS,"t_resynced_ns":$T_RESYNCED_NS,"delta_to_gone_ms":$DELTA_GONE_MS,"delta_to_agent_ready_ms":$DELTA_AGENT_MS,"delta_to_resynced_ms":$DELTA_RESYNC_MS,"timed_out":$TIMED_OUT}
EOF

  if [ "$p" -lt "$PROBE_COUNT" ]; then
    sleep "$PROBE_INTERVAL_S"
  fi
done

echo "[recovery] complete. ResilienceTimings.jsonl: $(wc -l < "$OUT") rows"
exit 0
