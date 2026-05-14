#!/bin/bash
# Scale scenario #3 (Node Churn / IP Churn) — drives node-level perturbation
# on the target cluster while CL2 measures across all clusters.
#
# Why this runs OUTSIDE CL2 (from execute.yml, NOT Method:Exec):
# The CL2 docker image (ghcr.io/azure/clusterloader2) has no `az` CLI and
# we don't control its build. `az` is a Python wheel with hundreds of MB
# of dependencies; pre-staging it the way we pre-stage the single-binary
# `kubectl` isn't feasible. So this script runs on the AzDO agent in a
# background subshell launched from execute.yml, in PARALLEL with the
# CL2 fanout (execute-parallel). CL2 on every cluster deploys baseline
# workload + measurements and sleeps for the scenario's duration window;
# the host-side churner drives the actual node ops; they meet again when
# execute.yml `wait`s for the churner PID after execute-parallel returns.
#
# Spec mapping (scale testing.txt:68-79):
#   * "Node scale-up/scale-down" + "Add/remove nodes continuously" → SCALE
#     scenario: cycle target's `default` pool count ±$DELTA for $CYCLES.
#   * "Node replacement (new IPs)" + "Force node recreation" → REPLACE
#     scenario: drain K nodes; `az vmss delete-instances` drops VMSS capacity
#     by K; then explicitly `az aks nodepool scale --node-count $ORIGINAL`
#     to refill (AKS doesn't auto-refill after delete-instances — build 67133
#     lesson). VMSS picks the next available instance IDs and provisions
#     brand-new VMs with brand-new private IPs.
#   * "Observe: IP update propagation, Temporary inconsistency windows" →
#     pre/post node InternalIP snapshots, per-op duration, observed node
#     count post-op. Peer-side propagation is captured by the parallel
#     CL2 measurements (cilium / clustermesh-metrics / node-churn.yaml).
#
# Sentinel-based readiness barrier (rubber-duck design review blocker #1):
# Per-cluster CL2 writes $SENTINEL_DIR/ready-<context> as the FIRST
# measurement step. The churner waits up to NODE_CHURN_READY_TIMEOUT_SECONDS
# for ALL $CLUSTER_COUNT sentinels before the first nodepool op, so peers
# are confirmed observing before stimulus begins. If quorum isn't reached,
# the churner aborts WITH cleanup (restore pool to original count) and
# emits scenario_valid=false so Kusto queries can drop the run.
#
# Trap-based finalizer (rubber-duck blocker #4):
# An EXIT trap unconditionally restores the target pool to original node
# count and waits for Succeeded + Ready, capped at NODE_CHURN_FINALIZER_TIMEOUT.
# If finalizer can't restore, emits cleanup_failed=true and execute.yml
# breaks out of the share-infra loop (no further scenarios run on a
# half-scaled cluster).
#
# Positional args (passed by execute.yml):
#   $1  SCENARIO                          node-churn-{scale,replace,combined}
#   $2  TARGET_CLUSTER_NAME               AKS cluster name (== kubectl context)
#   $3  TARGET_RESOURCE_GROUP             AKS RG (same RG as `az aks show`)
#   $4  TARGET_NODEPOOL                   workload pool name (always `default`)
#   $5  REPORT_DIR                        absolute path; timing JSON lands here
#   $6  SENTINEL_DIR                      absolute path; CL2 writes sentinels here
#   $7  CLUSTER_COUNT                     expected number of ready sentinels
#   $8  NODE_CHURN_CYCLES                 SCALE: cycles of (up+down)
#   $9  NODE_CHURN_DELTA                  SCALE: ±N per half-cycle
#   $10 NODE_CHURN_SETTLE_SECONDS         sleep between ops
#   $11 NODE_REPLACE_BATCH_SIZE           REPLACE: # of VMSS instances to delete
#   $12 NODE_CHURN_READY_TIMEOUT_SECONDS  ready-sentinel poll timeout
#   $13 EXPECTED_DURATION_SECONDS         CL2's matching sleep window
#   $14 TARGET_KUBECONFIG                  absolute path to target's kubeconfig
#                                          (from $HOME/.kube/<role>.config; passed
#                                          explicitly so we don't have to derive
#                                          role from target_cluster_name)
#
# Exit codes:
#   0 — always (soft-fail). The timing JSON's scenario_valid / cleanup_failed /
#       per-op succeeded flags are the load-bearing signals. Exiting non-zero
#       would cascade-fail the CL2 step → AzDO marks step failed → collect
#       still runs (because execute.yml's share-infra loop also soft-fails)
#       but the AzDO UI gets noisier than the actual data quality.

set -uo pipefail

SCENARIO="${1:?scenario required: node-churn-scale|node-churn-replace|node-churn-combined}"
TARGET_CLUSTER_NAME="${2:?target cluster name required}"
TARGET_RESOURCE_GROUP="${3:?target resource group required}"
TARGET_NODEPOOL="${4:-default}"
REPORT_DIR="${5:?report dir required}"
SENTINEL_DIR="${6:?sentinel dir required}"
CLUSTER_COUNT="${7:?cluster count required}"
NODE_CHURN_CYCLES="${8:-3}"
NODE_CHURN_DELTA="${9:-5}"
NODE_CHURN_SETTLE_SECONDS="${10:-60}"
NODE_REPLACE_BATCH_SIZE="${11:-10}"
NODE_CHURN_READY_TIMEOUT_SECONDS="${12:-300}"
EXPECTED_DURATION_SECONDS="${13:-1500}"
TARGET_KUBECONFIG="${14:-}"

# Internal bounds (not exposed via positional args — fine-tuned per scenario
# class, not per matrix entry).
NODE_CHURN_OP_TIMEOUT_SECONDS=900         # per `az aks nodepool scale` op
NODE_CHURN_FINALIZER_TIMEOUT_SECONDS=900  # cleanup pool restore
NODE_REPLACE_DRAIN_TIMEOUT_SECONDS=300    # per node drain
NODE_REPLACE_WAIT_TIMEOUT_SECONDS=1500    # for kubelet Ready after refill (build 67133: bumped 1200→1500 — refill provisioning + bootstrap can take 12-15 min on a fresh VM)

mkdir -p "$REPORT_DIR" "$SENTINEL_DIR"
TIMING_FILE="${REPORT_DIR}/NodeChurnTimings_${TARGET_CLUSTER_NAME}.json"

log() {
  echo "node-churner: $*"
}

err() {
  echo "node-churner ERROR: $*" >&2
}

# Resolve kubectl — prefer PATH; fall back to the pre-staged binary that
# execute.yml puts at $CL2_CONFIG_DIR/kubectl for Method:Exec scripts. The
# host AzDO agent should already have kubectl, but we don't want a brittle
# dependency on agent image version. SENTINEL_DIR is $CL2_CONFIG_DIR/sentinels
# by execute.yml's convention, so its parent is $CL2_CONFIG_DIR.
if command -v kubectl >/dev/null 2>&1; then
  KUBECTL=kubectl
elif [ -x "${SENTINEL_DIR%/sentinels*}/kubectl" ]; then
  KUBECTL="${SENTINEL_DIR%/sentinels*}/kubectl"
  log "using pre-staged kubectl at ${KUBECTL}"
else
  err "kubectl not in PATH and no pre-staged binary found at ${SENTINEL_DIR%/sentinels*}/kubectl"
  KUBECTL=""
fi

if ! command -v az >/dev/null 2>&1; then
  err "az CLI not in PATH on AzDO agent — cannot run node-churn scenario; aborting"
  cat > "$TIMING_FILE" <<EOF
{
  "scenario": "${SCENARIO}",
  "target_context": "${TARGET_CLUSTER_NAME}",
  "target_cluster_name": "${TARGET_CLUSTER_NAME}",
  "target_resource_group": "${TARGET_RESOURCE_GROUP}",
  "target_nodepool": "${TARGET_NODEPOOL}",
  "original_node_count": 0,
  "ready_quorum_reached": false,
  "scenario_valid": false,
  "cleanup_failed": false,
  "truncated": false,
  "started_epoch": $(date +%s),
  "ended_epoch": $(date +%s),
  "duration_seconds": 0,
  "ops": [],
  "error": "az CLI missing"
}
EOF
  exit 0
fi

if ! command -v jq >/dev/null 2>&1; then
  err "jq not in PATH on AzDO agent — required for timing JSON construction; aborting"
  # We can't use jq for the partial JSON, but the inline heredoc above
  # doesn't depend on jq.
  cat > "$TIMING_FILE" <<EOF
{
  "scenario": "${SCENARIO}",
  "target_context": "${TARGET_CLUSTER_NAME}",
  "target_cluster_name": "${TARGET_CLUSTER_NAME}",
  "target_resource_group": "${TARGET_RESOURCE_GROUP}",
  "target_nodepool": "${TARGET_NODEPOOL}",
  "original_node_count": 0,
  "ready_quorum_reached": false,
  "scenario_valid": false,
  "cleanup_failed": false,
  "truncated": false,
  "started_epoch": $(date +%s),
  "ended_epoch": $(date +%s),
  "duration_seconds": 0,
  "ops": [],
  "error": "jq missing"
}
EOF
  exit 0
fi

log "scenario=${SCENARIO} target=${TARGET_CLUSTER_NAME} pool=${TARGET_NODEPOOL}"
log "params cycles=${NODE_CHURN_CYCLES} delta=${NODE_CHURN_DELTA} settle=${NODE_CHURN_SETTLE_SECONDS}s replace_batch=${NODE_REPLACE_BATCH_SIZE}"
log "cl2 sleep window=${EXPECTED_DURATION_SECONDS}s; ready quorum=${CLUSTER_COUNT} sentinels (timeout ${NODE_CHURN_READY_TIMEOUT_SECONDS}s)"

# Persistent debug log — captures EVERY abort path's diagnostic dump so
# postmortem doesn't depend on AzDO retaining stdout. Lives alongside
# NodeChurnTimings_*.json in the per-cluster report dir, gets uploaded
# with the rest of the artifacts. Survives task cancellation.
DEBUG_LOG="${REPORT_DIR}/node-churner-debug.log"
: > "$DEBUG_LOG"

# State vars referenced by debug_dump — initialized early so any abort
# path (before main scenario dispatch) can call debug_dump safely under
# `set -u`. They're re-initialized to their authoritative values later
# when the scenario actually runs.
STARTED_EPOCH=$(date +%s)
READY_QUORUM_REACHED=false
SCENARIO_VALID=true
CLEANUP_FAILED=false
TRUNCATED=false
CIRCUIT_BROKEN=false
OPS_JSON='[]'
ORIGINAL_NODE_COUNT=0
NODE_RESOURCE_GROUP=""
TARGET_VMSS=""

debug_dump() {
  local _label="$1"
  {
    echo ""
    echo "================================================================"
    echo "=== ${_label} at $(date -u +"%Y-%m-%dT%H:%M:%SZ") (epoch=$(date +%s))"
    echo "================================================================"
    echo "-- runtime params --"
    echo "scenario=${SCENARIO} target_cluster_name=${TARGET_CLUSTER_NAME} target_rg=${TARGET_RESOURCE_GROUP}"
    echo "target_nodepool=${TARGET_NODEPOOL} target_vmss=${TARGET_VMSS:-unset} NRG=${NODE_RESOURCE_GROUP:-unset}"
    echo "original_node_count=${ORIGINAL_NODE_COUNT:-unset} cluster_count_quorum=${CLUSTER_COUNT}"
    echo "ready_quorum_reached=${READY_QUORUM_REACHED} scenario_valid=${SCENARIO_VALID} circuit_broken=${CIRCUIT_BROKEN} cleanup_failed=${CLEANUP_FAILED} truncated=${TRUNCATED}"
    echo "TARGET_KUBECONFIG=${TARGET_KUBECONFIG:-unset} KUBECTL=${KUBECTL:-unset}"
    echo ""
    echo "-- sentinel dir listing (${SENTINEL_DIR}) --"
    ls -la "$SENTINEL_DIR" 2>&1 || echo "(ls failed)"
    echo ""
    echo "-- az aks nodepool show (target) --"
    az aks nodepool show \
      --cluster-name "$TARGET_CLUSTER_NAME" \
      --resource-group "$TARGET_RESOURCE_GROUP" \
      --name "$TARGET_NODEPOOL" \
      --query '{count:count, provisioningState:provisioningState, powerState:powerState, vmSize:vmSize}' \
      -o json 2>&1 || echo "(az aks nodepool show failed)"
    echo ""
    if [ -n "${TARGET_VMSS:-}" ] && [ -n "${NODE_RESOURCE_GROUP:-}" ]; then
      echo "-- az vmss show (target VMSS sku.capacity) --"
      az vmss show --resource-group "$NODE_RESOURCE_GROUP" --name "$TARGET_VMSS" \
        --query '{capacity:sku.capacity, provisioningState:provisioningState}' \
        -o json 2>&1 || echo "(az vmss show failed)"
      echo ""
      echo "-- az vmss list-instances (count + ids) --"
      az vmss list-instances --resource-group "$NODE_RESOURCE_GROUP" --name "$TARGET_VMSS" \
        --query 'length([])' -o tsv 2>&1 || echo "(az vmss list-instances failed)"
    fi
    echo ""
    if [ -n "${KUBECTL:-}" ] && [ -n "${TARGET_KUBECONFIG:-}" ] && [ -f "$TARGET_KUBECONFIG" ]; then
      echo "-- kubectl get nodes (target cluster) --"
      KUBECONFIG="$TARGET_KUBECONFIG" "$KUBECTL" --context "$TARGET_CLUSTER_NAME" \
        get nodes -l "agentpool=${TARGET_NODEPOOL}" -o wide 2>&1 | head -30 || echo "(kubectl get nodes failed)"
      echo ""
      echo "-- target node internal IPs --"
      KUBECONFIG="$TARGET_KUBECONFIG" "$KUBECTL" --context "$TARGET_CLUSTER_NAME" \
        get nodes -l "agentpool=${TARGET_NODEPOOL}" \
        -o jsonpath='{range .items[*]}{.metadata.name}{" "}{.status.addresses[?(@.type=="InternalIP")].address}{"\n"}{end}' 2>&1 || true
    else
      echo "-- kubectl skipped (no KUBECTL or kubeconfig) --"
    fi
    echo ""
    echo "-- ops recorded so far --"
    echo "$OPS_JSON" | jq -r '.[] | "op#\(.op_index) \(.op_type) succeeded=\(.succeeded) duration=\(.duration_seconds)s observed_nodes=\(.observed_node_count) error=\"\(.error)\""' 2>&1 || echo "$OPS_JSON"
    echo "================================================================"
    echo ""
  } | tee -a "$DEBUG_LOG"
}

# write_aborted_timing — emit a minimal timing JSON for any early-exit
# code path (az missing, jq missing, can't resolve nodepool / VMSS, etc.)
# so collect.py picks up evidence that the scenario was attempted.
write_aborted_timing() {
  local _msg="$1"
  local _now
  _now=$(date +%s)
  cat > "$TIMING_FILE" <<EOF
{
  "scenario": "${SCENARIO}",
  "target_context": "${TARGET_CLUSTER_NAME}",
  "target_cluster_name": "${TARGET_CLUSTER_NAME}",
  "target_resource_group": "${TARGET_RESOURCE_GROUP}",
  "target_nodepool": "${TARGET_NODEPOOL}",
  "target_node_resource_group": "",
  "target_vmss": "",
  "original_node_count": 0,
  "ready_quorum_reached": false,
  "scenario_valid": false,
  "cleanup_failed": false,
  "truncated": false,
  "started_epoch": ${_now},
  "ended_epoch": ${_now},
  "duration_seconds": 0,
  "ops": [],
  "error": "${_msg}"
}
EOF
}

# -----------------------------------------------------------------------------
# Resolve original pool size + VMSS info
# -----------------------------------------------------------------------------
ORIGINAL_NODE_COUNT=$(az aks nodepool show \
  --cluster-name "$TARGET_CLUSTER_NAME" \
  --resource-group "$TARGET_RESOURCE_GROUP" \
  --name "$TARGET_NODEPOOL" \
  --query count -o tsv 2>/dev/null || echo "")
if [ -z "$ORIGINAL_NODE_COUNT" ] || ! [[ "$ORIGINAL_NODE_COUNT" =~ ^[0-9]+$ ]]; then
  err "could not resolve original node count for ${TARGET_CLUSTER_NAME}/${TARGET_NODEPOOL}; aborting"
  write_aborted_timing "could not resolve original node count for ${TARGET_CLUSTER_NAME}/${TARGET_NODEPOOL}"
  exit 0
fi
log "original node count = ${ORIGINAL_NODE_COUNT}"

# AKS puts VMSS in the node resource group ("MC_<rg>_<cluster>_<region>").
NODE_RESOURCE_GROUP=$(az aks show \
  --resource-group "$TARGET_RESOURCE_GROUP" \
  --name "$TARGET_CLUSTER_NAME" \
  --query nodeResourceGroup -o tsv 2>/dev/null || echo "")
if [ -z "$NODE_RESOURCE_GROUP" ]; then
  err "could not resolve nodeResourceGroup for ${TARGET_CLUSTER_NAME}; aborting"
  write_aborted_timing "could not resolve nodeResourceGroup for ${TARGET_CLUSTER_NAME}"
  exit 0
fi

# Discover the VMSS backing this nodepool. AKS tags VMSS with
# aks-managed-poolName=<nodepool>. Exactly one match expected.
TARGET_VMSS=$(az vmss list \
  --resource-group "$NODE_RESOURCE_GROUP" \
  --query "[?tags.\"aks-managed-poolName\"=='${TARGET_NODEPOOL}'].name | [0]" \
  -o tsv 2>/dev/null || echo "")
if [ -z "$TARGET_VMSS" ]; then
  err "could not resolve VMSS for pool ${TARGET_NODEPOOL} in ${NODE_RESOURCE_GROUP}; aborting"
  write_aborted_timing "could not resolve VMSS for pool ${TARGET_NODEPOOL} in ${NODE_RESOURCE_GROUP}"
  exit 0
fi
log "target VMSS=${TARGET_VMSS} in NRG=${NODE_RESOURCE_GROUP}"

# -----------------------------------------------------------------------------
# Timing-JSON accumulator. We keep state in shell vars + an ops jq array, and
# rewrite the timing file at every milestone so a crashed/SIGKILL'd run still
# leaves a partial-state file behind.
#
# Note: STARTED_EPOCH / *_FAILED / *_VALID / OPS_JSON are already initialized
# above (right after DEBUG_LOG) so debug_dump callable from any early-exit
# path. Don't re-initialize here.
# -----------------------------------------------------------------------------

write_timing_file() {
  local _ended _dur
  _ended=$(date +%s)
  _dur=$(( _ended - STARTED_EPOCH ))
  jq -n \
    --arg scenario "$SCENARIO" \
    --arg target_context "$TARGET_CLUSTER_NAME" \
    --arg target_cluster_name "$TARGET_CLUSTER_NAME" \
    --arg target_resource_group "$TARGET_RESOURCE_GROUP" \
    --arg target_nodepool "$TARGET_NODEPOOL" \
    --arg target_node_resource_group "$NODE_RESOURCE_GROUP" \
    --arg target_vmss "$TARGET_VMSS" \
    --argjson original_node_count "$ORIGINAL_NODE_COUNT" \
    --argjson ready_quorum_reached "$READY_QUORUM_REACHED" \
    --argjson scenario_valid "$SCENARIO_VALID" \
    --argjson cleanup_failed "$CLEANUP_FAILED" \
    --argjson truncated "$TRUNCATED" \
    --argjson started_epoch "$STARTED_EPOCH" \
    --argjson ended_epoch "$_ended" \
    --argjson duration_seconds "$_dur" \
    --argjson ops "$OPS_JSON" \
    '{scenario:$scenario, target_context:$target_context,
      target_cluster_name:$target_cluster_name,
      target_resource_group:$target_resource_group,
      target_nodepool:$target_nodepool,
      target_node_resource_group:$target_node_resource_group,
      target_vmss:$target_vmss,
      original_node_count:$original_node_count,
      ready_quorum_reached:$ready_quorum_reached,
      scenario_valid:$scenario_valid,
      cleanup_failed:$cleanup_failed,
      truncated:$truncated,
      started_epoch:$started_epoch,
      ended_epoch:$ended_epoch,
      duration_seconds:$duration_seconds,
      ops:$ops}' > "${TIMING_FILE}.tmp" && mv "${TIMING_FILE}.tmp" "$TIMING_FILE"
}

# Append one op record to OPS_JSON. Args:
#   $1 op_index, $2 op_type, $3 start_epoch, $4 end_epoch,
#   $5 succeeded (true|false), $6 observed_node_count,
#   $7 pre_state_json  — JSON object {"ips":[...], "names":[...]} ('{}' = empty)
#   $8 post_state_json — JSON object {"ips":[...], "names":[...]} ('{}' = empty)
#   $9 error_message (empty string OK)
#
# Build 67155 lesson: pre_ip_set/post_ip_set alone is a FLAWED replacement
# signal because Azure VNet allocator immediately reuses freed private IPs
# (we deleted vmss-instance 19 at 10.1.0.19; the replacement got 10.1.0.19
# again). Authoritative signal is NODE NAME delta (VMSS instance IDs are
# monotonic — vmss00000j → vmss00000k — not reused). jq below computes
# BOTH new_ip_count and new_node_count; downstream queries should prefer
# new_node_count for "did replacement actually happen".
record_op() {
  local _idx="$1" _type="$2" _t0="$3" _t1="$4" _ok="$5" _ncount="$6"
  local _pre="$7" _post="$8" _err="${9:-}"
  local _dur=$(( _t1 - _t0 ))
  OPS_JSON=$(jq -c \
    --argjson idx "$_idx" \
    --arg type "$_type" \
    --argjson t0 "$_t0" \
    --argjson t1 "$_t1" \
    --argjson dur "$_dur" \
    --argjson ok "$_ok" \
    --argjson ncount "$_ncount" \
    --argjson pre "$_pre" \
    --argjson post "$_post" \
    --arg err "$_err" \
    '. + [{
       op_index:$idx, op_type:$type, start_epoch:$t0, end_epoch:$t1,
       duration_seconds:$dur, succeeded:$ok, observed_node_count:$ncount,
       pre_ip_set:    ($pre.ips   // []),
       post_ip_set:   ($post.ips  // []),
       pre_node_names:  ($pre.names  // []),
       post_node_names: ($post.names // []),
       new_ip_count:   ([($post.ips   // [])[] | select(. as $p | (($pre.ips   // []) | index($p)) | not)] | length),
       new_node_count: ([($post.names // [])[] | select(. as $p | (($pre.names // []) | index($p)) | not)] | length),
       error:$err
     }]' \
    <<< "$OPS_JSON")
  write_timing_file
}

# Wait for VMSS provisioningState=Succeeded with timeout. Returns 0 on success,
# 1 on timeout. Polls every 10s.
wait_vmss_succeeded() {
  local _timeout="${1:-$NODE_CHURN_OP_TIMEOUT_SECONDS}"
  local _deadline=$(( $(date +%s) + _timeout ))
  while [ "$(date +%s)" -lt "$_deadline" ]; do
    local _state
    _state=$(az aks nodepool show \
      --cluster-name "$TARGET_CLUSTER_NAME" \
      --resource-group "$TARGET_RESOURCE_GROUP" \
      --name "$TARGET_NODEPOOL" \
      --query provisioningState -o tsv 2>/dev/null || echo "Unknown")
    if [ "$_state" = "Succeeded" ]; then
      return 0
    fi
    sleep 10
  done
  return 1
}

# Resolve target kubeconfig — TARGET_KUBECONFIG (positional arg 14) is
# the authoritative path passed by execute.yml from clusters_with_kubeconfig.
# Fallbacks (legacy / robustness) below.
resolve_target_kubeconfig() {
  local _kc="$TARGET_KUBECONFIG"
  if [ -n "$_kc" ] && [ -f "$_kc" ]; then
    echo "$_kc"; return
  fi
  _kc="$HOME/.kube/mesh-${TARGET_CLUSTER_NAME#clustermesh-}.config"
  if [ -f "$_kc" ]; then
    echo "$_kc"; return
  fi
  _kc="$HOME/.kube/config"
  if [ -f "$_kc" ]; then
    echo "$_kc"; return
  fi
  echo ""
}

# Run `kubectl get nodes -o json` against the target cluster, capturing
# BOTH stdout and stderr. Logs stderr to DEBUG_LOG so we can postmortem
# failure modes (auth errors, network, label-selector drift) — build
# 67126 lost this visibility because the old kubectl invocations had
# `2>/dev/null`.
#
# Returns 0 on success and prints the JSON to stdout; returns 1 on
# kubectl failure and prints nothing.
target_kubectl_get_nodes_json() {
  local _kc _out _rc
  _kc=$(resolve_target_kubeconfig)
  if [ -z "$_kc" ] || [ -z "$KUBECTL" ]; then
    {
      echo "===== kubectl get nodes: NO kubeconfig/kubectl ($(date -u +%FT%TZ)) ====="
      echo "TARGET_KUBECONFIG=${TARGET_KUBECONFIG:-unset}"
      echo "resolved=${_kc:-empty} KUBECTL=${KUBECTL:-empty}"
    } >> "$DEBUG_LOG"
    return 1
  fi
  _out=$(KUBECONFIG="$_kc" "$KUBECTL" --context "$TARGET_CLUSTER_NAME" \
    get nodes -o json 2>>"$DEBUG_LOG")
  _rc=$?
  if [ "$_rc" -ne 0 ] || [ -z "$_out" ]; then
    {
      echo "===== kubectl get nodes FAILED rc=${_rc} at $(date -u +%FT%TZ) ====="
      echo "kubeconfig=${_kc} context=${TARGET_CLUSTER_NAME}"
      echo "(stderr appended above by 2>>)"
    } >> "$DEBUG_LOG"
    return 1
  fi
  echo "$_out"
  return 0
}

# Filter nodes by TARGET_VMSS providerID — robust against AKS agentpool
# label key drift (newer AKS clusters prefer kubernetes.azure.com/agentpool
# over the legacy `agentpool` key). VMSS name is unique within the cluster
# and exact-match; also implicitly excludes prompool VMSS.
#
# Emits "node_name vmss_instance_id" lines on stdout, one per matched node.
target_nodes_in_target_vmss() {
  local _json
  _json=$(target_kubectl_get_nodes_json) || return 1
  echo "$_json" | jq -r --arg vmss "$TARGET_VMSS" '
    .items[]
    | select(.spec.providerID
        | contains("/virtualMachineScaleSets/" + $vmss + "/virtualMachines/"))
    | "\(.metadata.name) " + (.spec.providerID | split("/virtualMachines/")[1])
  ' 2>>"$DEBUG_LOG"
}

# Observe current node count on target cluster from K8s side. Returns "" on
# kubectl failure — caller treats as "unknown observed count".
observe_node_count() {
  local _lines
  _lines=$(target_nodes_in_target_vmss) || { echo ""; return; }
  echo "$_lines" | grep -c . | tr -d ' '
}

# Snapshot current Internal IPs AND node names for nodes in TARGET_VMSS.
# Returns a JSON object {"ips":[...], "names":[...]} on stdout.
#
# Build 67155 lesson: capture BOTH ips and names. IPs alone are unreliable
# as a replacement signal because Azure VNet allocator immediately reuses
# freed IPs. VMSS instance IDs (embedded in node names) are monotonic →
# names are the authoritative replacement signal.
#
# On kubectl failure, returns '{"ips":[],"names":[]}' (jq logic later
# handles empty arrays correctly: new_*_count == count of "post" entries).
snapshot_node_state() {
  local _json
  _json=$(target_kubectl_get_nodes_json) || { echo '{"ips":[],"names":[]}'; return; }
  echo "$_json" | jq -c --arg vmss "$TARGET_VMSS" '
    [ .items[]
      | select(.spec.providerID
          | contains("/virtualMachineScaleSets/" + $vmss + "/virtualMachines/"))
    ] as $matched
    | {
        ips:   [$matched[] | .status.addresses[] | select(.type=="InternalIP") | .address],
        names: [$matched[] | .metadata.name]
      }' 2>>"$DEBUG_LOG" || echo '{"ips":[],"names":[]}'
}

# Legacy compatibility shim — some call sites only need the IP set.
# New code should prefer snapshot_node_state.
snapshot_node_ips() {
  snapshot_node_state | jq -c '.ips' 2>>"$DEBUG_LOG" || echo "[]"
}

# -----------------------------------------------------------------------------
# Finalizer — runs on EVERY exit path (trap). Idempotent.
# -----------------------------------------------------------------------------
finalizer() {
  local _exit_rc=$?
  log "finalizer: starting (exit_rc=${_exit_rc}); restoring pool to original_node_count=${ORIGINAL_NODE_COUNT}"
  local _current
  _current=$(az aks nodepool show \
    --cluster-name "$TARGET_CLUSTER_NAME" \
    --resource-group "$TARGET_RESOURCE_GROUP" \
    --name "$TARGET_NODEPOOL" \
    --query count -o tsv 2>/dev/null || echo "$ORIGINAL_NODE_COUNT")
  if [ "$_current" = "$ORIGINAL_NODE_COUNT" ]; then
    log "finalizer: pool already at original_node_count; checking provisioningState"
    if wait_vmss_succeeded "$NODE_CHURN_FINALIZER_TIMEOUT_SECONDS"; then
      log "finalizer: pool already restored and Succeeded"
      write_timing_file
      return 0
    fi
    log "finalizer: pool count matches but provisioningState != Succeeded; will explicitly scale to nudge reconcile"
  fi
  # Even if VMSS desired-count != AKS desired-count (after a VMSS instance
  # delete), `az aks nodepool scale` with the original count re-syncs both.
  if ! az aks nodepool scale \
      --cluster-name "$TARGET_CLUSTER_NAME" \
      --resource-group "$TARGET_RESOURCE_GROUP" \
      --name "$TARGET_NODEPOOL" \
      --node-count "$ORIGINAL_NODE_COUNT" \
      --no-wait --only-show-errors >/dev/null 2>&1; then
    err "finalizer: az aks nodepool scale to ${ORIGINAL_NODE_COUNT} failed"
    CLEANUP_FAILED=true
    debug_dump "FINALIZER cleanup_failed (az aks nodepool scale to original failed)"
    write_timing_file
    return 1
  fi
  if ! wait_vmss_succeeded "$NODE_CHURN_FINALIZER_TIMEOUT_SECONDS"; then
    err "finalizer: pool did NOT reach Succeeded within ${NODE_CHURN_FINALIZER_TIMEOUT_SECONDS}s"
    CLEANUP_FAILED=true
    debug_dump "FINALIZER cleanup_failed (provisioningState != Succeeded)"
    write_timing_file
    return 1
  fi
  log "finalizer: pool restored to ${ORIGINAL_NODE_COUNT}, Succeeded"
  write_timing_file
  return 0
}
trap finalizer EXIT

# Initial state — write the file so even an early abort leaves a row.
write_timing_file

# -----------------------------------------------------------------------------
# Ready-sentinel barrier
# -----------------------------------------------------------------------------
log "ready-barrier: waiting for ${CLUSTER_COUNT} CL2 sentinel(s) in ${SENTINEL_DIR}"
BARRIER_DEADLINE=$(( $(date +%s) + NODE_CHURN_READY_TIMEOUT_SECONDS ))
while [ "$(date +%s)" -lt "$BARRIER_DEADLINE" ]; do
  _count=$(find "$SENTINEL_DIR" -maxdepth 1 -name 'ready-*' -type f 2>/dev/null | wc -l | tr -d ' ')
  if [ "$_count" -ge "$CLUSTER_COUNT" ]; then
    log "ready-barrier: quorum reached (${_count}/${CLUSTER_COUNT})"
    READY_QUORUM_REACHED=true
    write_timing_file
    break
  fi
  sleep 5
done
if [ "$READY_QUORUM_REACHED" != true ]; then
  err "ready-barrier: quorum NOT reached after ${NODE_CHURN_READY_TIMEOUT_SECONDS}s (saw ${_count:-0}/${CLUSTER_COUNT}); aborting scenario"
  SCENARIO_VALID=false
  debug_dump "READY-BARRIER ABORT (saw ${_count:-0}/${CLUSTER_COUNT})"
  write_timing_file
  exit 0
fi

# -----------------------------------------------------------------------------
# Scenario dispatch
# -----------------------------------------------------------------------------
OP_INDEX=0
WALL_DEADLINE=$(( STARTED_EPOCH + EXPECTED_DURATION_SECONDS ))

run_scale_phase() {
  log "scale phase: ${NODE_CHURN_CYCLES} cycles × (up by ${NODE_CHURN_DELTA}, down by ${NODE_CHURN_DELTA})"
  local _cur="$ORIGINAL_NODE_COUNT"
  for _c in $(seq 1 "$NODE_CHURN_CYCLES"); do
    # Circuit breaker — stop if a previous op tripped it.
    if [ "$CIRCUIT_BROKEN" = true ]; then
      log "scale phase: circuit broken; skipping remaining cycles"
      break
    fi
    # ---- scale UP ----
    local _target=$(( _cur + NODE_CHURN_DELTA ))
    OP_INDEX=$(( OP_INDEX + 1 ))
    log "cycle ${_c}/${NODE_CHURN_CYCLES} op#${OP_INDEX} scale_up: ${_cur} → ${_target}"
    local _t0=$(date +%s)
    local _err=""
    local _ok=true
    if ! az aks nodepool scale \
        --cluster-name "$TARGET_CLUSTER_NAME" \
        --resource-group "$TARGET_RESOURCE_GROUP" \
        --name "$TARGET_NODEPOOL" \
        --node-count "$_target" \
        --only-show-errors 2>/tmp/node-churner-az.err; then
      _err=$(tr '\n' ' ' < /tmp/node-churner-az.err | head -c 500)
      _ok=false
      # OperationNotAllowed / throttling — structural error, trip circuit breaker.
      if echo "$_err" | grep -qiE 'OperationNotAllowed|TooManyRequests|429|conflict'; then
        err "scale phase: structural Azure RP error on scale_up; tripping circuit breaker"
        CIRCUIT_BROKEN=true
        SCENARIO_VALID=false
        debug_dump "CIRCUIT-BROKEN on scale_up op#${OP_INDEX} (Azure RP structural error)"
      fi
    fi
    local _t1=$(date +%s)
    local _ncount
    _ncount=$(observe_node_count)
    [ -z "$_ncount" ] && _ncount=0
    record_op "$OP_INDEX" "scale_up" "$_t0" "$_t1" "$_ok" "$_ncount" '{}' '{}' "$_err"
    [ "$_ok" = true ] && _cur="$_target"
    sleep "$NODE_CHURN_SETTLE_SECONDS"

    if [ "$CIRCUIT_BROKEN" = true ]; then
      break
    fi
    # ---- scale DOWN ----
    _target=$(( _cur - NODE_CHURN_DELTA ))
    if [ "$_target" -lt 1 ]; then _target=1; fi
    OP_INDEX=$(( OP_INDEX + 1 ))
    log "cycle ${_c}/${NODE_CHURN_CYCLES} op#${OP_INDEX} scale_down: ${_cur} → ${_target}"
    _t0=$(date +%s)
    _err=""
    _ok=true
    if ! az aks nodepool scale \
        --cluster-name "$TARGET_CLUSTER_NAME" \
        --resource-group "$TARGET_RESOURCE_GROUP" \
        --name "$TARGET_NODEPOOL" \
        --node-count "$_target" \
        --only-show-errors 2>/tmp/node-churner-az.err; then
      _err=$(tr '\n' ' ' < /tmp/node-churner-az.err | head -c 500)
      _ok=false
      if echo "$_err" | grep -qiE 'OperationNotAllowed|TooManyRequests|429|conflict'; then
        err "scale phase: structural Azure RP error on scale_down; tripping circuit breaker"
        CIRCUIT_BROKEN=true
        SCENARIO_VALID=false
        debug_dump "CIRCUIT-BROKEN on scale_down op#${OP_INDEX} (Azure RP structural error)"
      fi
    fi
    _t1=$(date +%s)
    _ncount=$(observe_node_count)
    [ -z "$_ncount" ] && _ncount=0
    record_op "$OP_INDEX" "scale_down" "$_t0" "$_t1" "$_ok" "$_ncount" '{}' '{}' "$_err"
    [ "$_ok" = true ] && _cur="$_target"
    sleep "$NODE_CHURN_SETTLE_SECONDS"
  done
  log "scale phase: complete (ended at cycle current_count=${_cur})"
}

run_replace_phase() {
  log "replace phase: drain + delete ${NODE_REPLACE_BATCH_SIZE} VMSS instance(s); AKS auto-refills"
  if [ -z "$KUBECTL" ]; then
    err "replace phase: kubectl unavailable; skipping (cannot drain)"
    CIRCUIT_BROKEN=true
    SCENARIO_VALID=false
    debug_dump "REPLACE-PHASE aborted (KUBECTL unset)"
    return
  fi

  # ---- 1. Pre-snapshot state (IPs + node names) + pick K nodes ----
  # Both ips AND names are recorded so post-run analysis can use whichever
  # signal is appropriate. Build 67155 showed IPs are unreliable (Azure
  # reuses freed private IPs); node names (VMSS instance suffix) are the
  # authoritative replacement marker.
  local _pre_state
  _pre_state=$(snapshot_node_state)
  local _kubeconfig
  _kubeconfig=$(resolve_target_kubeconfig)
  if [ -z "$_kubeconfig" ]; then
    err "replace phase: could not resolve a usable kubeconfig path; aborting"
    CIRCUIT_BROKEN=true
    SCENARIO_VALID=false
    debug_dump "REPLACE-PHASE aborted (no usable kubeconfig)"
    return
  fi

  # Pick K target VMSS instance ids via the VMSS-providerID filter
  # (label-key independent, build 67126 lesson).
  local _node_iid_lines
  _node_iid_lines=$(target_nodes_in_target_vmss)
  if [ -z "$_node_iid_lines" ]; then
    err "replace phase: 0 nodes match VMSS=${TARGET_VMSS}; aborting"
    # Dump raw kubectl output so postmortem can see WHY (label drift,
    # providerID format change, auth blip).
    {
      echo "===== REPLACE-PHASE no-nodes diagnostic ====="
      echo "expected VMSS=${TARGET_VMSS}"
      echo "kubeconfig=${_kubeconfig}"
      echo "-- kubectl get nodes -o wide (raw, no label filter) --"
      KUBECONFIG="$_kubeconfig" "$KUBECTL" --context "$TARGET_CLUSTER_NAME" \
        get nodes -o wide 2>&1 | head -50 || true
      echo "-- kubectl get nodes -o jsonpath providerID dump --"
      KUBECONFIG="$_kubeconfig" "$KUBECTL" --context "$TARGET_CLUSTER_NAME" \
        get nodes -o jsonpath='{range .items[*]}{.metadata.name}{" "}{.spec.providerID}{"\n"}{end}' 2>&1 \
        | head -50 || true
    } >> "$DEBUG_LOG"
    CIRCUIT_BROKEN=true
    SCENARIO_VALID=false
    debug_dump "REPLACE-PHASE aborted (0 nodes match VMSS=${TARGET_VMSS})"
    return
  fi

  # Shuffle and take first K.
  local _selected
  if command -v shuf >/dev/null 2>&1; then
    _selected=$(echo "$_node_iid_lines" | shuf | head -n "$NODE_REPLACE_BATCH_SIZE")
  else
    _selected=$(echo "$_node_iid_lines" \
      | awk 'BEGIN{srand()} {print rand()" "$0}' \
      | sort -k1,1n | head -n "$NODE_REPLACE_BATCH_SIZE" | cut -d" " -f2-)
  fi
  local _selected_count
  _selected_count=$(echo "$_selected" | wc -l | tr -d ' ')
  log "replace phase: selected ${_selected_count} nodes for replacement"
  echo "$_selected" | awk '{print "  - "$1" (vmss-instance "$2")"}'

  # ---- 2. Drain selected nodes (one Op record per drain) ----
  local _instance_ids_csv=""
  while IFS= read -r _line; do
    [ -z "$_line" ] && continue
    local _node_name="${_line%% *}"
    local _instance_id="${_line##* }"
    OP_INDEX=$(( OP_INDEX + 1 ))
    log "op#${OP_INDEX} replace_drain: ${_node_name} (vmss-instance ${_instance_id})"
    local _t0=$(date +%s)
    local _err=""
    local _ok=true
    # Cordon first (idempotent + cheap), then drain. timeout caps per-node
    # so a stuck PDB doesn't block the whole batch.
    KUBECONFIG="$_kubeconfig" "$KUBECTL" --context "$TARGET_CLUSTER_NAME" \
      cordon "$_node_name" >/dev/null 2>&1 || true
    if ! KUBECONFIG="$_kubeconfig" "$KUBECTL" --context "$TARGET_CLUSTER_NAME" \
        drain "$_node_name" --ignore-daemonsets --delete-emptydir-data --force \
        --grace-period=30 \
        --timeout="${NODE_REPLACE_DRAIN_TIMEOUT_SECONDS}s" 2>/tmp/node-churner-drain.err; then
      _err=$(tr '\n' ' ' < /tmp/node-churner-drain.err | head -c 500)
      _ok=false
      # Drain failure isn't fatal — AKS will still drain the node when we
      # delete the VMSS instance underneath. Record and continue.
      log "replace phase: drain ${_node_name} returned non-zero; continuing (VMSS delete will force)"
    fi
    local _t1=$(date +%s)
    record_op "$OP_INDEX" "replace_drain" "$_t0" "$_t1" "$_ok" 0 '{}' '{}' "$_err"
    if [ -n "$_instance_ids_csv" ]; then
      _instance_ids_csv="${_instance_ids_csv} ${_instance_id}"
    else
      _instance_ids_csv="${_instance_id}"
    fi
  done <<< "$_selected"

  if [ "$CIRCUIT_BROKEN" = true ]; then
    log "replace phase: circuit broken before VMSS delete"
    return
  fi
  if [ -z "$_instance_ids_csv" ]; then
    err "replace phase: no instance IDs collected; aborting"
    CIRCUIT_BROKEN=true
    SCENARIO_VALID=false
    debug_dump "REPLACE-PHASE aborted (no instance ids after drain loop)"
    return
  fi

  # ---- 3. Delete selected VMSS instances in a single batched call ----
  OP_INDEX=$(( OP_INDEX + 1 ))
  log "op#${OP_INDEX} replace_delete: deleting VMSS instances [${_instance_ids_csv}]"
  local _t0=$(date +%s)
  local _err=""
  local _ok=true
  # shellcheck disable=SC2086  # word splitting intentional for instance ids
  if ! az vmss delete-instances \
      --resource-group "$NODE_RESOURCE_GROUP" \
      --name "$TARGET_VMSS" \
      --instance-ids ${_instance_ids_csv} \
      --only-show-errors 2>/tmp/node-churner-az.err; then
    _err=$(tr '\n' ' ' < /tmp/node-churner-az.err | head -c 500)
    _ok=false
    if echo "$_err" | grep -qiE 'OperationNotAllowed|TooManyRequests|429|conflict'; then
      err "replace phase: structural Azure RP error on vmss delete-instances; tripping circuit breaker"
      CIRCUIT_BROKEN=true
      SCENARIO_VALID=false
      debug_dump "CIRCUIT-BROKEN on replace_delete op#${OP_INDEX} (Azure RP structural error)"
    fi
  fi
  local _t1=$(date +%s)
  local _ncount
  _ncount=$(observe_node_count)
  [ -z "$_ncount" ] && _ncount=0
  record_op "$OP_INDEX" "replace_delete" "$_t0" "$_t1" "$_ok" "$_ncount" '{}' '{}' "$_err"

  if [ "$CIRCUIT_BROKEN" = true ]; then return; fi

  # ---- 4. Explicit refill via AKS nodepool scale ----
  # Build 67133 lesson: `az vmss delete-instances` drops VMSS capacity by K,
  # and AKS observes the drop (nodepool count goes from N to N-K) but does
  # NOT auto-refill back to N. The finalizer's `az aks nodepool scale
  # --node-count $ORIGINAL` succeeded → so the explicit re-scale IS the
  # correct primitive. Run it here as a dedicated op so the timing JSON
  # records the refill latency separately from the kubelet-Ready wait.
  #
  # AKS-side refill picks up the next available VMSS instance ID and
  # provisions a brand-new VM with a brand-new InternalIP — exactly the
  # IP-churn signal the spec asks for.
  OP_INDEX=$(( OP_INDEX + 1 ))
  log "op#${OP_INDEX} replace_refill: az aks nodepool scale → ${ORIGINAL_NODE_COUNT} (re-add ${NODE_REPLACE_BATCH_SIZE} replacement(s))"
  _t0=$(date +%s)
  _err=""
  _ok=true
  if ! az aks nodepool scale \
      --cluster-name "$TARGET_CLUSTER_NAME" \
      --resource-group "$TARGET_RESOURCE_GROUP" \
      --name "$TARGET_NODEPOOL" \
      --node-count "$ORIGINAL_NODE_COUNT" \
      --only-show-errors 2>/tmp/node-churner-az.err; then
    _err=$(tr '\n' ' ' < /tmp/node-churner-az.err | head -c 500)
    _ok=false
    if echo "$_err" | grep -qiE 'OperationNotAllowed|TooManyRequests|429|conflict'; then
      err "replace phase: structural Azure RP error on replace_refill; tripping circuit breaker"
      CIRCUIT_BROKEN=true
      SCENARIO_VALID=false
      debug_dump "CIRCUIT-BROKEN on replace_refill op#${OP_INDEX} (Azure RP structural error)"
    fi
  fi
  _t1=$(date +%s)
  _ncount=$(observe_node_count)
  [ -z "$_ncount" ] && _ncount=0
  record_op "$OP_INDEX" "replace_refill" "$_t0" "$_t1" "$_ok" "$_ncount" '{}' '{}' "$_err"

  if [ "$CIRCUIT_BROKEN" = true ]; then return; fi

  # ---- 5. Wait for K8s Ready node count to return to ORIGINAL ----
  # AKS nodepool scale returns when Azure provisioning is complete, but
  # kubelet on the new VM still needs to register + reach Ready. Poll
  # kubectl until Ready count == ORIGINAL (not just VMSS provisioningState).
  OP_INDEX=$(( OP_INDEX + 1 ))
  log "op#${OP_INDEX} replace_wait: waiting for ${ORIGINAL_NODE_COUNT} Ready nodes in pool"
  _t0=$(date +%s)
  _err=""
  _ok=false
  local _wait_deadline=$(( _t0 + NODE_REPLACE_WAIT_TIMEOUT_SECONDS ))
  local _ready_count=0
  while [ "$(date +%s)" -lt "$_wait_deadline" ]; do
    # Count Ready nodes whose providerID is in our target VMSS (label-
    # selector-agnostic; build 67126 regression fix).
    local _ready_json
    _ready_json=$(target_kubectl_get_nodes_json 2>/dev/null)
    if [ -n "$_ready_json" ]; then
      _ready_count=$(echo "$_ready_json" | jq -r --arg vmss "$TARGET_VMSS" '
        [ .items[]
          | select(.spec.providerID | contains("/virtualMachineScaleSets/" + $vmss + "/virtualMachines/"))
          | .status.conditions[]
          | select(.type=="Ready" and .status=="True") ] | length' 2>/dev/null || echo 0)
    else
      _ready_count=0
    fi
    if [ "$_ready_count" -ge "$ORIGINAL_NODE_COUNT" ]; then
      _ok=true
      break
    fi
    sleep 10
  done
  _t1=$(date +%s)
  local _post_state
  _post_state=$(snapshot_node_state)
  if [ "$_ok" != true ]; then
    _err="replace_wait: timeout after ${NODE_REPLACE_WAIT_TIMEOUT_SECONDS}s; ready=${_ready_count}/${ORIGINAL_NODE_COUNT}"
    err "$_err"
    SCENARIO_VALID=false
    debug_dump "REPLACE_WAIT timeout (ready=${_ready_count}/${ORIGINAL_NODE_COUNT})"
  fi
  record_op "$OP_INDEX" "replace_wait" "$_t0" "$_t1" "$_ok" "$_ready_count" "$_pre_state" "$_post_state" "$_err"
  # Pull new_node_count from the just-recorded op for the summary log line.
  local _new_node_count _new_ip_count
  _new_node_count=$(echo "$OPS_JSON" | jq -r '.[-1].new_node_count')
  _new_ip_count=$(echo "$OPS_JSON" | jq -r '.[-1].new_ip_count')
  log "replace phase: complete (new_node_count=${_new_node_count} [authoritative], new_ip_count=${_new_ip_count} [informational; Azure may reuse freed IPs])"
}

case "$SCENARIO" in
  node-churn-scale)
    run_scale_phase
    ;;
  node-churn-replace)
    run_replace_phase
    ;;
  node-churn-combined)
    run_scale_phase
    if [ "$CIRCUIT_BROKEN" != true ]; then
      log "transitioning from scale phase to replace phase"
      sleep "$NODE_CHURN_SETTLE_SECONDS"
      run_replace_phase
    else
      log "scale phase circuit-broken; skipping replace phase"
    fi
    ;;
  *)
    err "unknown scenario '${SCENARIO}'; expected node-churn-{scale,replace,combined}"
    SCENARIO_VALID=false
    ;;
esac

# Truncation check: did we run past CL2's sleep window?
if [ "$(date +%s)" -gt "$WALL_DEADLINE" ]; then
  log "WARN: churner ran past CL2 sleep window (${EXPECTED_DURATION_SECONDS}s); peer measurements may be truncated"
  TRUNCATED=true
fi

write_timing_file
log "scenario complete; finalizer will run via EXIT trap"
exit 0
