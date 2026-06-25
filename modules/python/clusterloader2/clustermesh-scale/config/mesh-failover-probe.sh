#!/usr/bin/env bash
# mesh-failover-probe.sh
#
# Single-cluster backend-failure probe (gap #4).
# Customer Q: "If I lose all backends in cluster A, how long until peer
# clusters route around it?"
#
# Mechanism per iteration (uses SCALE 0 pattern for clean recoverable
# failure injection, not pod-delete which races against the Deployment):
#   1. Pick victim = max numeric mesh-N role
#   2. Find Deployments matching $selector_label on victim, snapshot replicas
#   3. PRE-STATE: verify each peer's BPF lb map currently contains the
#      victim's backend IPs (else mesh hasn't converged; fail iter loudly)
#   4. SCALE TO 0 those Deployments. Capture t_scale_down_ns
#   5. PARALLEL-poll each peer's BPF lb list for victim IPs to GO AWAY
#      → record per-peer t_absent_ns + reroute_ms
#   6. RESTORE Deployments to original replica counts
#   7. Wait for backend count to return to baseline on victim before
#      next iter (prevents next iter snapshotting partial pool)
#
# Output: $REPORT_DIR/$LEADER_ROLE-MeshFailoverProbe.jsonl
#
# Required env (from execute.yml launch_mesh_failover_probe):
#   CL2_FAILOVER_PROBE_ENABLED=true
#   CLUSTERMESH_CLUSTERS_JSON, REPORT_DIR, SCENARIO_NAME, LEADER_ROLE, PROBE_NS
# Optional:
#   CL2_FAILOVER_PROBE_COUNT (default 3)
#   CL2_FAILOVER_PROBE_INTERVAL_S (default 60)
#   CL2_FAILOVER_PROBE_TIMEOUT_S (default 180)
#   CL2_FAILOVER_SELECTOR_LABEL (default group=clustermesh-propagation-probe)

set -uo pipefail

readonly POLL_INTERVAL=2

probe_count="${CL2_FAILOVER_PROBE_COUNT:-3}"
probe_interval="${CL2_FAILOVER_PROBE_INTERVAL_S:-60}"
probe_timeout="${CL2_FAILOVER_PROBE_TIMEOUT_S:-180}"
selector_label="${CL2_FAILOVER_SELECTOR_LABEL:-group=clustermesh-propagation-probe}"
probe_ns="${PROBE_NS:-clustermesh-probe-1}"

log() { echo "[failover-probe $(date -u +%H:%M:%S)] $*" >&2; }

emit() {
  local _type="$1"
  local _extra="${2:-}"
  [ -z "$_extra" ] && _extra='{}'
  printf '%s\n' "$(jq -nc \
    --arg type "$_type" \
    --arg scenario "${SCENARIO_NAME:-mesh-failover-probe}" \
    --arg role "${LEADER_ROLE:-mesh-1}" \
    --arg victim "$victim_role" \
    --argjson n "$n_clusters" \
    --arg ts "$(date -u +%Y-%m-%dT%H:%M:%S.%3NZ)" \
    --argjson extra "$_extra" \
    '{type:$type, scenario:$scenario, leader_role:$role, victim_role:$victim, n_clusters:$n, timestamp:$ts} * $extra' \
  )" >> "$report_jsonl"
}

# ---------- ARG / ENV ----------
report_dir="${REPORT_DIR:?REPORT_DIR required}"
scenario="${SCENARIO_NAME:-mesh-failover-probe}"
leader_role="${LEADER_ROLE:-mesh-1}"
clusters_json="${CLUSTERMESH_CLUSTERS_JSON:?CLUSTERMESH_CLUSTERS_JSON required}"

mkdir -p "$report_dir"
report_jsonl="${report_dir}/${leader_role}-MeshFailoverProbe.jsonl"
: > "$report_jsonl"

n_clusters=$(jq -r 'length' "$clusters_json")
if [ "$n_clusters" -lt 2 ]; then
  log "ERROR: need >=2 clusters (got $n_clusters)"
  exit 1
fi

victim_role=$(jq -r '[.[] | .role | capture("mesh-(?<n>[0-9]+)") | .n | tonumber] | max as $m | "mesh-\($m)"' "$clusters_json")
victim_kc=$(jq -r --arg v "$victim_role" '.[] | select(.role==$v) | .kubeconfig' "$clusters_json")
victim_ctx=$(jq -r --arg v "$victim_role" '.[] | select(.role==$v) | .context // .name' "$clusters_json")

log "n_clusters=$n_clusters victim=$victim_role selector=$selector_label probe_ns=$probe_ns"

# Discover Deployments to scale + their original replica counts
# Returns space-separated "name:replicas" pairs.
discover_victim_deployments() {
  KUBECONFIG="$victim_kc" kubectl --context "$victim_ctx" -n "$probe_ns" \
    get deployment -l "$selector_label" \
    -o jsonpath='{range .items[*]}{.metadata.name}{":"}{.spec.replicas}{" "}{end}' 2>/dev/null
}

victim_deployments=$(discover_victim_deployments)
if [ -z "$victim_deployments" ]; then
  log "ERROR: no Deployments match selector $selector_label in $probe_ns on victim — workload not deployed?"
  exit 1
fi
log "victim Deployments: $victim_deployments"

# Cleanup trap: if iter is interrupted, restore original replica counts.
cleanup() {
  local rc=$?
  log "cleanup: restoring victim Deployments to original replica counts"
  for entry in $victim_deployments; do
    local _name="${entry%%:*}" _replicas="${entry##*:}"
    KUBECONFIG="$victim_kc" kubectl --context "$victim_ctx" -n "$probe_ns" \
      scale "deployment/$_name" --replicas="$_replicas" >/dev/null 2>&1 || true
  done
  emit "summary" "{\"probe_count\":$probe_count,\"exit_status\":\"$exit_status\"}"
  exit $rc
}
exit_status="pass"
trap cleanup EXIT

snapshot_victim_backend_ips() {
  # Restrict to pods OWNED BY a ReplicaSet (i.e., owned by one of our
  # victim Deployments). Excludes standalone Pods created by other
  # mechanisms (e.g., FIRST_PACKET probe pod) that share the same
  # selector label but won't be removed by `kubectl scale deployment`.
  KUBECONFIG="$victim_kc" kubectl --context "$victim_ctx" -n "$probe_ns" \
    get pods -l "$selector_label" -o json 2>/dev/null \
    | jq -r '.items[] | select(.metadata.ownerReferences != null and (.metadata.ownerReferences[] | .kind=="ReplicaSet")) | .status.podIP // empty' \
    | sort -u | grep -v '^$' || true
}

# Pre-state check: ensure ALL known victim IPs are present in given peer's
# lb list (mesh fully converged before we kill anything). Returns 0 if
# pre-state OK, 1 if not.
peer_has_victim_ips() {
  local _kc="$1" _ctx="$2" _victim_ips_file="$3"
  local _cil _out
  _cil=$(KUBECONFIG="$_kc" kubectl --context "$_ctx" -n kube-system get pods -l k8s-app=cilium -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)
  [ -z "$_cil" ] && return 1
  _out=$(KUBECONFIG="$_kc" kubectl --context "$_ctx" -n kube-system exec "$_cil" -c cilium-agent -- \
    cilium-dbg bpf lb list 2>/dev/null || true)
  local _missing=0
  while read -r _ip; do
    [ -z "$_ip" ] && continue
    if ! echo "$_out" | grep -qF "${_ip}:"; then _missing=$((_missing+1)); fi
  done < "$_victim_ips_file"
  [ $_missing -eq 0 ]
}

# Wait for ALL victim IPs to disappear from peer's lb list. Writes
# nanosecond timestamp (or 0) to $outfile.
wait_victim_absent_from_peer_lb() {
  local _kc="$1" _ctx="$2" _victim_ips_file="$3" _deadline_s="$4" _outfile="$5"
  local _start _now _cil _out _t_absent=0
  _start=$(date +%s)
  _cil=$(KUBECONFIG="$_kc" kubectl --context "$_ctx" -n kube-system get pods -l k8s-app=cilium -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)
  while true; do
    _now=$(date +%s)
    if [ $((_now - _start)) -ge "$_deadline_s" ]; then break; fi
    if [ -n "$_cil" ]; then
      _out=$(KUBECONFIG="$_kc" kubectl --context "$_ctx" -n kube-system exec "$_cil" -c cilium-agent -- \
        cilium-dbg bpf lb list 2>/dev/null || true)
      local _any_present=false
      while read -r _ip; do
        [ -z "$_ip" ] && continue
        if echo "$_out" | grep -qF "${_ip}:"; then _any_present=true; break; fi
      done < "$_victim_ips_file"
      if [ "$_any_present" = "false" ]; then _t_absent=$(date +%s%N); break; fi
    fi
    sleep "$POLL_INTERVAL"
  done
  echo "$_t_absent" > "$_outfile"
}

# Wait for victim's backend pod count to return to baseline (recovery).
wait_victim_backends_restored() {
  local _expected="$1" _deadline_s="$2"
  local _start _count
  _start=$(date +%s)
  while true; do
    _count=$(KUBECONFIG="$victim_kc" kubectl --context "$victim_ctx" -n "$probe_ns" \
      get pods -l "$selector_label" --field-selector=status.phase=Running -o name 2>/dev/null | wc -l)
    if [ "$_count" -ge "$_expected" ]; then return 0; fi
    local _now; _now=$(date +%s)
    [ $((_now - _start)) -ge "$_deadline_s" ] && return 1
    sleep 3
  done
}

# Build peer specs (non-victim)
peer_specs=""
while IFS= read -r entry; do
  role=$(echo "$entry" | jq -r '.role')
  kc=$(echo "$entry" | jq -r '.kubeconfig')
  ctx=$(echo "$entry" | jq -r '.context // .name')
  [ "$role" = "$victim_role" ] && continue
  peer_specs="${peer_specs}${role}|${kc}|${ctx}|"
done < <(jq -c '.[]' "$clusters_json")

# ---------- MAIN ----------
for iter in $(seq 1 "$probe_count"); do
  log "iter=$iter/$probe_count"

  victim_ips_file=$(mktemp)
  snapshot_victim_backend_ips > "$victim_ips_file"
  victim_ip_count=$(wc -l < "$victim_ips_file")
  if [ "$victim_ip_count" -eq 0 ]; then
    log "iter=$iter: no backend pods on victim — workload may still be coming up; skipping"
    emit "iter_skipped" "{\"iter\":$iter,\"reason\":\"no_backends_on_victim\"}"
    rm -f "$victim_ips_file"
    sleep "$probe_interval"
    continue
  fi

  # PRE-STATE: verify each peer has victim IPs in its lb map
  pre_ok=true
  IFS='|' read -ra parts <<< "$peer_specs"
  for ((i=0; i<${#parts[@]}; i+=3)); do
    [ -z "${parts[i]:-}" ] && continue
    local_kc="${parts[i+1]}" local_ctx="${parts[i+2]}"
    if ! peer_has_victim_ips "$local_kc" "$local_ctx" "$victim_ips_file"; then
      log "iter=$iter: pre-state FAIL — peer ${parts[i]} does not have victim IPs in lb map (mesh not converged)"
      pre_ok=false
      break
    fi
  done
  if [ "$pre_ok" = "false" ]; then
    emit "iter_skipped" "{\"iter\":$iter,\"reason\":\"pre_state_mesh_not_converged\"}"
    rm -f "$victim_ips_file"
    sleep "$probe_interval"
    continue
  fi

  emit "iter_start" "{\"iter\":$iter,\"victim_backend_ips_count\":$victim_ip_count}"

  # SCALE DOWN to 0
  t_scale_down_ns=$(date +%s%N)
  for entry in $victim_deployments; do
    name="${entry%%:*}"
    KUBECONFIG="$victim_kc" kubectl --context "$victim_ctx" -n "$probe_ns" \
      scale "deployment/$name" --replicas=0 >/dev/null 2>&1 || true
  done

  # PARALLEL-poll each peer for victim IPs to disappear
  poll_outdir=$(mktemp -d)
  IFS='|' read -ra parts <<< "$peer_specs"
  for ((i=0; i<${#parts[@]}; i+=3)); do
    [ -z "${parts[i]:-}" ] && continue
    role="${parts[i]}" kc="${parts[i+1]}" ctx="${parts[i+2]}"
    wait_victim_absent_from_peer_lb "$kc" "$ctx" "$victim_ips_file" "$probe_timeout" "$poll_outdir/$role" &
  done
  wait

  # Emit per-peer rows + iter summary
  max_reroute_ms=0
  observers_complete=0
  observers_total=0
  IFS='|' read -ra parts <<< "$peer_specs"
  for ((i=0; i<${#parts[@]}; i+=3)); do
    [ -z "${parts[i]:-}" ] && continue
    role="${parts[i]}"
    observers_total=$((observers_total + 1))
    t_absent_ns=$(cat "$poll_outdir/$role" 2>/dev/null || echo 0)
    if [ "$t_absent_ns" -ne 0 ]; then
      reroute_ms=$(( (t_absent_ns - t_scale_down_ns) / 1000000 ))
      observers_complete=$((observers_complete + 1))
      [ "$reroute_ms" -gt "$max_reroute_ms" ] && max_reroute_ms=$reroute_ms
      emit "peer_reroute" "{\"iter\":$iter,\"peer_role\":\"$role\",\"t_scale_down_ns\":$t_scale_down_ns,\"t_absent_ns\":$t_absent_ns,\"reroute_ms\":$reroute_ms,\"timed_out\":false}"
    else
      emit "peer_reroute" "{\"iter\":$iter,\"peer_role\":\"$role\",\"t_scale_down_ns\":$t_scale_down_ns,\"t_absent_ns\":0,\"reroute_ms\":null,\"timed_out\":true}"
    fi
  done

  # RESTORE replica counts
  for entry in $victim_deployments; do
    name="${entry%%:*}" replicas="${entry##*:}"
    KUBECONFIG="$victim_kc" kubectl --context "$victim_ctx" -n "$probe_ns" \
      scale "deployment/$name" --replicas="$replicas" >/dev/null 2>&1 || true
  done

  # Wait for backend count to return before next iter (60s budget)
  if ! wait_victim_backends_restored "$victim_ip_count" 60; then
    log "iter=$iter: WARN backends did not fully recover within 60s"
  fi

  emit "iter_summary" "{\"iter\":$iter,\"observers_complete\":$observers_complete,\"observers_total\":$observers_total,\"max_reroute_ms\":$max_reroute_ms}"

  rm -rf "$poll_outdir" "$victim_ips_file"

  if [ "$iter" -lt "$probe_count" ]; then
    sleep "$probe_interval"
  fi
done

log "DONE — exit_status=$exit_status"
