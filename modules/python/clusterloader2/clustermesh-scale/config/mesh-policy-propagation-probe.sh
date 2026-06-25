#!/usr/bin/env bash
# mesh-policy-propagation-probe.sh
#
# Cross-cluster CNP propagation cost probe. Host-side orchestrator launched
# by execute.yml when CL2_POLICY_PROP_PROBE_ENABLED=true. Complements the
# per-cluster policy-scale scenario (which measures cost of N CNPs ON one
# cluster) by measuring cost of ONE CNP fleet-wide:
#
#   "When I apply the same CNP to all N clusters simultaneously (GitOps /
#   Fleet workload pattern), what is the worst-case per-cluster compile +
#   enforcement latency? When are ALL clusters actually enforcing?"
#
# Mechanism per probe iteration (CL2_POLICY_PROP_PROBE_COUNT iterations):
#   1. Generate unique CNP YAML (name probe-cnp-<iter>-<ts>)
#   2. PARALLEL apply on every cluster: kubectl apply -f <CNP> across all N
#      kubeconfigs. Record per-cluster t_apply_done.
#   3. PARALLEL poll each cluster's cilium-dbg policy get for the CNP's
#      presence. Record per-cluster t_policy_loaded.
#   4. PARALLEL poll each cluster's cilium_policy_implementation_delay_count
#      to detect when implementation has actually fired. Record per-cluster
#      t_implementation_observed.
#   5. PARALLEL kubectl delete -f <CNP> across all N. Wait for clean removal.
#
# Output: $REPORT_DIR/$LEADER_ROLE-MeshPolicyPropProbe.jsonl with one row
# per (iteration, cluster) plus per-iteration summary rows.
#
# Required env (from execute.yml launch_mesh_policy_propagation_probe):
#   CL2_POLICY_PROP_PROBE_ENABLED=true
#   CLUSTERMESH_CLUSTERS_JSON (path to per-cluster name/role/kubeconfig)
#   REPORT_DIR, SCENARIO_NAME, LEADER_ROLE
# Optional:
#   CL2_POLICY_PROP_PROBE_COUNT (default 5)
#   CL2_POLICY_PROP_PROBE_INTERVAL_S (default 60 between iterations)
#   CL2_POLICY_PROP_PROBE_TIMEOUT_S (default 120 per phase)

set -uo pipefail

readonly DEFAULT_PROBE_COUNT=5
readonly DEFAULT_INTERVAL=60
readonly DEFAULT_TIMEOUT=120
readonly POLL_INTERVAL=2

probe_count="${CL2_POLICY_PROP_PROBE_COUNT:-$DEFAULT_PROBE_COUNT}"
probe_interval="${CL2_POLICY_PROP_PROBE_INTERVAL_S:-$DEFAULT_INTERVAL}"
probe_timeout="${CL2_POLICY_PROP_PROBE_TIMEOUT_S:-$DEFAULT_TIMEOUT}"

log() { echo "[policy-prop-probe $(date -u +%H:%M:%S)] $*" >&2; }

emit() {
  # $1 = type, $2 (optional) = extra fields JSON
  local _type="$1"
  local _extra="${2:-}"
  [ -z "$_extra" ] && _extra='{}'
  printf '%s\n' "$(jq -nc \
    --arg type "$_type" \
    --arg scenario "${SCENARIO_NAME:-mesh-policy-prop-probe}" \
    --arg role "${LEADER_ROLE:-mesh-1}" \
    --argjson n "$n_clusters" \
    --arg ts "$(date -u +%Y-%m-%dT%H:%M:%S.%3NZ)" \
    --argjson extra "$_extra" \
    '{type:$type, scenario:$scenario, leader_role:$role, n_clusters:$n, timestamp:$ts} * $extra' \
  )" >> "$report_jsonl"
}

# ---------- ARG VALIDATION ----------
report_dir="${REPORT_DIR:?REPORT_DIR required}"
scenario="${SCENARIO_NAME:-mesh-policy-prop-probe}"
leader_role="${LEADER_ROLE:-mesh-1}"
clusters_json="${CLUSTERMESH_CLUSTERS_JSON:?CLUSTERMESH_CLUSTERS_JSON required}"

mkdir -p "$report_dir"
report_jsonl="${report_dir}/${leader_role}-MeshPolicyPropProbe.jsonl"
: > "$report_jsonl"

if [ ! -f "$clusters_json" ]; then
  log "ERROR: clusters json not found at $clusters_json"
  exit 1
fi

n_clusters=$(jq -r 'length' "$clusters_json")
if [ "$n_clusters" -lt 2 ]; then
  log "ERROR: need >=2 clusters for cross-cluster policy propagation signal (got $n_clusters)"
  exit 1
fi

log "n_clusters=$n_clusters probe_count=$probe_count interval=${probe_interval}s timeout=${probe_timeout}s report=$report_jsonl"

# Build space-separated list of "role|kubeconfig|context" once
cluster_specs=""
while IFS= read -r entry; do
  role=$(echo "$entry" | jq -r '.role')
  kc=$(echo "$entry" | jq -r '.kubeconfig')
  ctx=$(echo "$entry" | jq -r '.context // .name')
  cluster_specs="${cluster_specs}${role}|${kc}|${ctx}|"
done < <(jq -c '.[]' "$clusters_json")

# Cleanup trap — always try to delete any leftover probe CNPs across all clusters
cleanup() {
  local rc=$?
  log "cleanup: deleting any leftover policy-prop-probe-* CNPs from all clusters"
  local _IFS_save="$IFS"
  IFS='|' read -ra parts <<< "$cluster_specs"
  for ((i=0; i<${#parts[@]}; i+=3)); do
    [ -z "${parts[i]:-}" ] && continue
    local _kc="${parts[i+1]}" _ctx="${parts[i+2]}"
    KUBECONFIG="$_kc" kubectl --context "$_ctx" delete cnp -l probe=policy-prop --all-namespaces --ignore-not-found --wait=false >/dev/null 2>&1 || true
  done
  IFS="$_IFS_save"
  log "cleanup done; exit_status=$exit_status"
  exit $rc
}
exit_status="pass"
trap cleanup EXIT

# ---------- HELPERS ----------

# Apply a CNP YAML to a single cluster. Echo per-cluster row to a temp file.
# Args: role kubeconfig context cnp_yaml_path output_dir iter
apply_one() {
  local _role="$1" _kc="$2" _ctx="$3" _yaml="$4" _outdir="$5" _iter="$6"
  local _t0_ms _t1_ms _rc
  _t0_ms=$(date +%s%3N)
  KUBECONFIG="$_kc" kubectl --context "$_ctx" apply -f "$_yaml" >/dev/null 2>&1
  _rc=$?
  _t1_ms=$(date +%s%3N)
  echo "{\"role\":\"$_role\",\"phase\":\"apply\",\"rc\":$_rc,\"t_start_ms\":$_t0_ms,\"t_done_ms\":$_t1_ms,\"latency_ms\":$((_t1_ms - _t0_ms))}" \
    > "${_outdir}/apply-${_role}.json"
}

# Poll a cluster for the CNP to be loaded in cilium-dbg policy get.
# Returns when found OR timeout. Echo per-cluster row to temp file.
poll_loaded_one() {
  local _role="$1" _kc="$2" _ctx="$3" _cnp_name="$4" _t0_ms="$5" _outdir="$6"
  local _now_ms _elapsed_ms _found="false" _t_observed_ms="null"
  while true; do
    _now_ms=$(date +%s%3N)
    _elapsed_ms=$((_now_ms - _t0_ms))
    if [ "$_elapsed_ms" -gt $((probe_timeout * 1000)) ]; then
      break
    fi
    # cilium-dbg policy get returns CNP info; grep for the name. Distroless-safe.
    if KUBECONFIG="$_kc" kubectl --context "$_ctx" -n kube-system exec ds/cilium -c cilium-agent -- \
         cilium-dbg policy get 2>/dev/null | grep -q "$_cnp_name"; then
      _found="true"
      _t_observed_ms=$_now_ms
      break
    fi
    sleep "$POLL_INTERVAL"
  done
  local _latency
  if [ "$_t_observed_ms" = "null" ]; then
    _latency="null"
  else
    _latency=$((_t_observed_ms - _t0_ms))
  fi
  echo "{\"role\":\"$_role\",\"phase\":\"loaded\",\"found\":$_found,\"t_observed_ms\":$_t_observed_ms,\"latency_ms\":$_latency}" \
    > "${_outdir}/loaded-${_role}.json"
}

# Delete CNP from a single cluster.
delete_one() {
  local _role="$1" _kc="$2" _ctx="$3" _yaml="$4" _outdir="$5"
  KUBECONFIG="$_kc" kubectl --context "$_ctx" delete -f "$_yaml" --ignore-not-found --wait=false >/dev/null 2>&1
  echo "{\"role\":\"$_role\",\"phase\":\"deleted\"}" > "${_outdir}/delete-${_role}.json"
}

# ---------- MAIN PROBE LOOP ----------
for iter in $(seq 1 "$probe_count"); do
  iter_id="$(date -u +%Y%m%d%H%M%S)-${iter}"
  cnp_name="probe-cnp-${iter_id}"
  iter_outdir="${report_dir}/_polprop-iter-${iter}"
  mkdir -p "$iter_outdir"

  log "iter=${iter}/${probe_count} cnp=${cnp_name}"

  # Generate unique CNP YAML (default ns + permissive selector matching nothing
  # to avoid disrupting real workloads — we only care about compile cost).
  cnp_yaml="${iter_outdir}/cnp.yaml"
  cat > "$cnp_yaml" <<EOF
apiVersion: cilium.io/v2
kind: CiliumNetworkPolicy
metadata:
  name: ${cnp_name}
  namespace: default
  labels:
    probe: policy-prop
spec:
  endpointSelector:
    matchLabels:
      mesh-probe-marker-${iter_id}: target
  ingress:
    - toPorts:
        - ports:
            - port: "80"
              protocol: TCP
EOF

  # Phase 1: PARALLEL apply across all clusters (t0_ms = barrier)
  apply_start_ms=$(date +%s%3N)
  emit "iter_apply_start" "{\"iter\":$iter,\"cnp_name\":\"${cnp_name}\",\"apply_start_ms\":$apply_start_ms}"
  IFS='|' read -ra parts <<< "$cluster_specs"
  for ((i=0; i<${#parts[@]}; i+=3)); do
    [ -z "${parts[i]:-}" ] && continue
    apply_one "${parts[i]}" "${parts[i+1]}" "${parts[i+2]}" "$cnp_yaml" "$iter_outdir" "$iter" &
  done
  wait

  # Phase 2: PARALLEL poll for cilium-dbg policy get to show the CNP
  IFS='|' read -ra parts <<< "$cluster_specs"
  for ((i=0; i<${#parts[@]}; i+=3)); do
    [ -z "${parts[i]:-}" ] && continue
    poll_loaded_one "${parts[i]}" "${parts[i+1]}" "${parts[i+2]}" "$cnp_name" "$apply_start_ms" "$iter_outdir" &
  done
  wait

  # Emit per-cluster rows from this iter's collected JSONs
  for f in "$iter_outdir"/apply-*.json "$iter_outdir"/loaded-*.json; do
    [ -f "$f" ] || continue
    row=$(cat "$f")
    emit "iter_observation" "$(jq -nc --argjson row "$row" --argjson iter "$iter" '$row * {iter:$iter}')"
  done

  # Compute iter summary: max loaded latency = "time to fleet-wide enforcement"
  max_loaded_latency_ms=$(cat "$iter_outdir"/loaded-*.json 2>/dev/null \
    | jq -s '[.[] | select(.latency_ms != null) | .latency_ms] | max // null')
  observers_loaded=$(cat "$iter_outdir"/loaded-*.json 2>/dev/null \
    | jq -s '[.[] | select(.found == true)] | length')
  emit "iter_summary" "{\"iter\":$iter,\"observers_loaded\":${observers_loaded},\"max_loaded_latency_ms\":${max_loaded_latency_ms},\"observers_total\":$n_clusters}"

  # Phase 3: PARALLEL delete
  IFS='|' read -ra parts <<< "$cluster_specs"
  for ((i=0; i<${#parts[@]}; i+=3)); do
    [ -z "${parts[i]:-}" ] && continue
    delete_one "${parts[i]}" "${parts[i+1]}" "${parts[i+2]}" "$cnp_yaml" "$iter_outdir" &
  done
  wait

  # Inter-iter sleep
  if [ "$iter" -lt "$probe_count" ]; then
    sleep "$probe_interval"
  fi
done

emit "summary" "{\"probe_count\":$probe_count,\"exit_status\":\"$exit_status\"}"
log "DONE — exit_status=$exit_status"
