#!/usr/bin/env bash
# mesh-restart-survival-probe.sh
#
# clustermesh-apiserver restart survival probe (gap #8).
# Customer Q: "If clustermesh-apiserver restarts (rolling update, eviction,
# OOM), do existing cross-cluster connections survive?"
#
# Mechanism per iteration:
#   1. Pick victim = lowest numeric mesh-N role (mesh-1).
#   2. Discover global Service DNS via labels on victim.
#   3. Per peer: `kubectl run` a curl pod with the loop AS THE POD'S MAIN
#      COMMAND (sh -c "for i in seq 1 N; do curl ... ; sleep 1; done").
#      Pod naturally exits when the loop ends. No `kubectl exec` race.
#   4. Capture pre-restart Deployment generation on victim.
#   5. Wait baseline_s into the loop.
#   6. `kubectl rollout restart deployment/clustermesh-apiserver` on victim.
#   7. Wait for rollout completion via `kubectl rollout status` AND verify
#      generation actually incremented (else flag restart_failed).
#   8. Wait post_settle_s + loop tail.
#   9. Wait for each curl pod to reach Succeeded/Failed phase, then
#      `kubectl logs` (loop wrote to stdout) and parse.
#  10. Per-peer: parse log, count transport-success (any non-000 HTTP code)
#      vs transport-fail (000 = curl couldn't reach the server); compute
#      survival_ratio = (total - conn_fail) / total, guarded with
#      `if total > 0 then ... else null end`.
#
# Output: $REPORT_DIR/$LEADER_ROLE-MeshRestartSurvivalProbe.jsonl
#
# Required env (from execute.yml launch_mesh_restart_survival_probe):
#   CL2_RESTART_SURVIVAL_PROBE_ENABLED=true
#   CLUSTERMESH_CLUSTERS_JSON, REPORT_DIR, SCENARIO_NAME, LEADER_ROLE, PROBE_NS
# Optional:
#   CL2_RESTART_SURVIVAL_PROBE_COUNT (default 2)
#   CL2_RESTART_SURVIVAL_PROBE_INTERVAL_S (default 180)
#   CL2_RESTART_SURVIVAL_PROBE_TIMEOUT_S (default 300) — rollout status wait
#   CL2_RESTART_SURVIVAL_BASELINE_S (default 10) — pre-restart curl-loop secs
#   CL2_RESTART_SURVIVAL_POST_SETTLE_S (default 10) — post-restart curl-loop tail
#   CL2_RESTART_SURVIVAL_DEPLOY_NAME (default clustermesh-apiserver)
#   CL2_RESTART_SURVIVAL_DEPLOY_NS (default kube-system)

set -uo pipefail

readonly CURL_IMAGE="mcr.microsoft.com/cbl-mariner/base/core:2.0"

probe_count="${CL2_RESTART_SURVIVAL_PROBE_COUNT:-2}"
probe_interval="${CL2_RESTART_SURVIVAL_PROBE_INTERVAL_S:-180}"
probe_timeout="${CL2_RESTART_SURVIVAL_PROBE_TIMEOUT_S:-300}"
baseline_s="${CL2_RESTART_SURVIVAL_BASELINE_S:-10}"
post_settle_s="${CL2_RESTART_SURVIVAL_POST_SETTLE_S:-10}"
probe_ns="${PROBE_NS:-clustermesh-probe-1}"
deploy_name="${CL2_RESTART_SURVIVAL_DEPLOY_NAME:-clustermesh-apiserver}"
deploy_ns="${CL2_RESTART_SURVIVAL_DEPLOY_NS:-kube-system}"

# Loop runs for baseline + restart-budget + post-settle seconds (bounded).
# Use probe_timeout as worst-case restart-budget.
loop_secs=$(( baseline_s + probe_timeout + post_settle_s ))

log() { echo "[restart-survival-probe $(date -u +%H:%M:%S)] $*" >&2; }

# ---------- ARG / ENV ----------
report_dir="${REPORT_DIR:?REPORT_DIR required}"
scenario="${SCENARIO_NAME:-mesh-restart-survival-probe}"
leader_role="${LEADER_ROLE:-mesh-1}"
clusters_json="${CLUSTERMESH_CLUSTERS_JSON:?CLUSTERMESH_CLUSTERS_JSON required}"

mkdir -p "$report_dir"
report_jsonl="${report_dir}/${leader_role}-MeshRestartSurvivalProbe.jsonl"
: > "$report_jsonl"

n_clusters=$(jq -r 'length' "$clusters_json")
if [ "$n_clusters" -lt 2 ]; then
  log "ERROR: need >=2 clusters (got $n_clusters)"
  exit 1
fi

victim_role=$(jq -r '[.[] | .role | capture("mesh-(?<n>[0-9]+)") | .n | tonumber] | min as $m | "mesh-\($m)"' "$clusters_json")
victim_kc=$(jq -r --arg v "$victim_role" '.[] | select(.role==$v) | .kubeconfig' "$clusters_json")
victim_ctx=$(jq -r --arg v "$victim_role" '.[] | select(.role==$v) | .context // .name' "$clusters_json")

log "n_clusters=$n_clusters victim=$victim_role deploy=$deploy_ns/$deploy_name loop_secs=$loop_secs"

emit() {
  local _type="$1"
  local _extra="${2:-}"
  [ -z "$_extra" ] && _extra='{}'
  printf '%s\n' "$(jq -nc \
    --arg type "$_type" \
    --arg scenario "$scenario" \
    --arg role "$leader_role" \
    --arg victim "$victim_role" \
    --argjson n "$n_clusters" \
    --arg ts "$(date -u +%Y-%m-%dT%H:%M:%S.%3NZ)" \
    --argjson extra "$_extra" \
    '{type:$type, scenario:$scenario, leader_role:$role, victim_role:$victim, n_clusters:$n, timestamp:$ts} * $extra' \
  )" >> "$report_jsonl"
}

exit_status="pass"

# Discover global Service via Deployment selector on victim.
# Backend pods have label `app: clustermesh-propagation-probe` (from the
# propagation-probe-workload module). Find a Service in PROBE_NS that
# selects them — the global Service exposed via global service DNS.
svc=$(KUBECONFIG="$victim_kc" kubectl --context "$victim_ctx" -n "$probe_ns" \
  get svc -o json 2>/dev/null \
  | jq -r '.items[] | select(.spec.selector["app"]=="clustermesh-propagation-probe") | .metadata.name' \
  | head -1)
if [ -z "$svc" ]; then
  # Fallback: any Service in PROBE_NS
  svc=$(KUBECONFIG="$victim_kc" kubectl --context "$victim_ctx" -n "$probe_ns" \
    get svc -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo "")
fi
if [ -z "$svc" ]; then
  log "ERROR: no Service in $probe_ns on victim — propagation-probe workload not deployed?"
  exit 1
fi
GLOBAL_SVC_DNS="${svc}.${probe_ns}.svc.cluster.local:80"
log "global Service DNS: $GLOBAL_SVC_DNS"

# Build peer specs (non-victim)
peer_specs=()
while IFS= read -r entry; do
  role=$(echo "$entry" | jq -r '.role')
  kc=$(echo "$entry" | jq -r '.kubeconfig')
  ctx=$(echo "$entry" | jq -r '.context // .name')
  [ "$role" = "$victim_role" ] && continue
  peer_specs+=("${role}|${kc}|${ctx}")
done < <(jq -c '.[]' "$clusters_json")

if [ "${#peer_specs[@]}" -lt 1 ]; then
  log "ERROR: no peer clusters after excluding victim"
  exit 1
fi

# Track curl pod names per iteration for cleanup
all_curl_pods=()
cleanup() {
  local rc=$?
  log "cleanup: deleting ${#all_curl_pods[@]} curl pods across peers"
  local entry _role _pod _kc _ctx
  for entry in "${all_curl_pods[@]}"; do
    _role="${entry%%:*}"
    _pod="${entry##*:}"
    _kc=$(jq -r --arg r "$_role" '.[] | select(.role==$r) | .kubeconfig' "$clusters_json")
    _ctx=$(jq -r --arg r "$_role" '.[] | select(.role==$r) | .context // .name' "$clusters_json")
    KUBECONFIG="$_kc" kubectl --context "$_ctx" -n "$probe_ns" \
      delete pod "$_pod" --grace-period=0 --force --wait=false >/dev/null 2>&1 || true
  done
  emit "summary" "{\"probe_count\":$probe_count,\"exit_status\":\"$exit_status\"}"
  exit $rc
}
trap cleanup EXIT

# Start a curl pod per peer. The pod's MAIN container runs the curl loop
# directly (no kubectl exec), writing each result line to STDOUT. Pod
# exits when the loop ends. We collect via `kubectl logs` later.
start_curl_pods() {
  local _iter="$1"
  local _names=()
  local entry _role _kc _ctx _pod
  # Loop emits CSV rows to stdout: epoch_ns,http_code
  # Bound by total iterations = loop_secs (1 per second).
  local _cmd
  _cmd="i=0; while [ \$i -lt ${loop_secs} ]; do code=\$(curl -s -m 2 -o /dev/null -w '%{http_code}' http://${GLOBAL_SVC_DNS}/ 2>/dev/null); echo \"\$(date +%s%N),\$code\"; i=\$((i+1)); sleep 1; done"
  for entry in "${peer_specs[@]}"; do
    _role="${entry%%|*}"
    local _rest="${entry#*|}"
    _kc="${_rest%%|*}"
    _ctx="${_rest##*|}"
    _pod="rs-curl-${_iter}-${_role}-$(date +%s | tail -c 5)"
    KUBECONFIG="$_kc" kubectl --context "$_ctx" -n "$probe_ns" run "$_pod" \
      --image="$CURL_IMAGE" --restart=Never --quiet \
      --labels="probe=restart-survival,iter=${_iter}" \
      --command -- sh -c "$_cmd" >/dev/null 2>&1 || true
    _names+=("${_role}:${_pod}")
  done
  # Wait for all pods to reach Running (so the loop's first row captures
  # real baseline). Bounded 30s.
  local _waited=0
  while [ $_waited -lt 30 ]; do
    local _all_ready=true
    for entry in "${_names[@]}"; do
      _role="${entry%%:*}"
      _pod="${entry##*:}"
      _kc=$(jq -r --arg r "$_role" '.[] | select(.role==$r) | .kubeconfig' "$clusters_json")
      _ctx=$(jq -r --arg r "$_role" '.[] | select(.role==$r) | .context // .name' "$clusters_json")
      local _phase
      _phase=$(KUBECONFIG="$_kc" kubectl --context "$_ctx" -n "$probe_ns" \
        get pod "$_pod" -o jsonpath='{.status.phase}' 2>/dev/null || echo "")
      [ "$_phase" != "Running" ] && _all_ready=false
    done
    $_all_ready && break
    sleep 1
    _waited=$((_waited + 1))
  done
  printf '%s\n' "${_names[@]}"
}

collect_curl_logs() {
  local _iter="$1" _outdir="$2"
  shift 2
  local entry _role _pod _kc _ctx _phase _waited
  for entry in "$@"; do
    _role="${entry%%:*}"
    _pod="${entry##*:}"
    _kc=$(jq -r --arg r "$_role" '.[] | select(.role==$r) | .kubeconfig' "$clusters_json")
    _ctx=$(jq -r --arg r "$_role" '.[] | select(.role==$r) | .context // .name' "$clusters_json")
    # Wait for pod to finish (Succeeded or Failed), bounded by loop_secs+30
    _waited=0
    while [ $_waited -lt $((loop_secs + 30)) ]; do
      _phase=$(KUBECONFIG="$_kc" kubectl --context "$_ctx" -n "$probe_ns" \
        get pod "$_pod" -o jsonpath='{.status.phase}' 2>/dev/null || echo "")
      case "$_phase" in
        Succeeded|Failed) break ;;
      esac
      sleep 2
      _waited=$((_waited + 2))
    done
    # Pull stdout — may be partial if pod was killed early
    KUBECONFIG="$_kc" kubectl --context "$_ctx" -n "$probe_ns" \
      logs "$_pod" >"$_outdir/$_role.csv" 2>/dev/null || true
  done
}

# Parse a per-peer results.csv. Emits a peer_survival event.
# transport-success = any non-000 HTTP code (curl reached the remote endpoint).
# transport-fail (conn_fail) = 000 (curl could not connect at all).
emit_peer_survival() {
  local _iter="$1" _role="$2" _csv="$3" _restart_start_ns="$4" _restart_done_ns="$5" _restart_duration_ms="$6" _restart_ok="$7"
  if [ ! -s "$_csv" ]; then
    emit "peer_survival" "{\"iter\":$_iter,\"peer_role\":\"$_role\",\"total\":0,\"transport_success\":0,\"conn_fail\":0,\"survival_ratio\":null,\"restart_window_survival_ratio\":null,\"note\":\"empty_results\",\"restart_ok\":$_restart_ok,\"restart_duration_ms\":$_restart_duration_ms}"
    return
  fi
  # Counts via awk to avoid grep -c exit-code quirk.
  local counts
  counts=$(awk -F, '
    BEGIN { t=0; cf=0; ts=0; httpok=0; first_cf=0; last_cf=0 }
    NF >= 2 {
      t++
      code = $2
      ts_ns = $1+0
      if (code == "000" || code == "") { cf++; if (first_cf==0) first_cf=ts_ns; last_cf=ts_ns }
      else { ts++; if (code == "200") httpok++ }
    }
    END { printf "%d %d %d %d %d %d\n", t, ts, cf, httpok, first_cf, last_cf }
  ' "$_csv")
  set -- $counts
  local total="$1" transport_success="$2" conn_fail="$3" http_200="$4" first_cf="$5" last_cf="$6"

  local during_total=0 during_cf=0
  local during_counts
  during_counts=$(awk -F, -v s="$_restart_start_ns" -v e="$_restart_done_ns" '
    BEGIN { dt=0; dcf=0 }
    NF >= 2 {
      ts_ns = $1+0
      if (ts_ns >= s && ts_ns <= e) {
        dt++
        if ($2 == "000" || $2 == "") dcf++
      }
    }
    END { printf "%d %d\n", dt, dcf }
  ' "$_csv")
  set -- $during_counts
  during_total="$1"
  during_cf="$2"

  emit "peer_survival" "$(jq -nc \
    --argjson iter "$_iter" \
    --arg role "$_role" \
    --argjson total "$total" \
    --argjson transport_success "$transport_success" \
    --argjson conn_fail "$conn_fail" \
    --argjson http_200 "$http_200" \
    --argjson first_cf "$first_cf" \
    --argjson last_cf "$last_cf" \
    --argjson during "$during_cf" \
    --argjson during_total "$during_total" \
    --argjson restart_ms "$_restart_duration_ms" \
    --argjson restart_ok "$_restart_ok" \
    '{iter:$iter, peer_role:$role, total:$total, transport_success:$transport_success, conn_fail:$conn_fail, http_200:$http_200,
      first_conn_fail_ns:$first_cf, last_conn_fail_ns:$last_cf,
      restart_window_total:$during_total, restart_window_conn_fail:$during,
      survival_ratio: (if $total > 0 then (($total - $conn_fail) / $total) else null end),
      restart_window_survival_ratio: (if $during_total > 0 then (($during_total - $during) / $during_total) else null end),
      restart_duration_ms:$restart_ms, restart_ok:$restart_ok}')"
}

# ---------- MAIN ----------
for iter in $(seq 1 "$probe_count"); do
  log "iter=$iter/$probe_count"
  emit "iter_start" "{\"iter\":$iter}"

  # Capture pre-restart Deployment generation
  pre_gen=$(KUBECONFIG="$victim_kc" kubectl --context "$victim_ctx" -n "$deploy_ns" \
    get "deployment/$deploy_name" -o jsonpath='{.metadata.generation}' 2>/dev/null || echo 0)
  if [ "$pre_gen" = "0" ] || [ -z "$pre_gen" ]; then
    log "iter=$iter: ERROR could not read Deployment $deploy_ns/$deploy_name generation; skipping"
    emit "iter_skipped" "{\"iter\":$iter,\"reason\":\"deployment_not_found\"}"
    continue
  fi

  # Start curl pods + read pod-name list (from stdout of start_curl_pods)
  mapfile -t curl_pods < <(start_curl_pods "$iter")
  all_curl_pods+=("${curl_pods[@]}")

  # Baseline
  sleep "$baseline_s"

  # RESTART
  restart_start_ns=$(date +%s%N)
  log "iter=$iter: restart $deploy_ns/$deploy_name (pre_gen=$pre_gen)"
  emit "restart_start" "{\"iter\":$iter,\"restart_start_ns\":$restart_start_ns,\"pre_gen\":$pre_gen}"
  KUBECONFIG="$victim_kc" kubectl --context "$victim_ctx" -n "$deploy_ns" \
    rollout restart "deployment/$deploy_name" >/dev/null 2>&1 || \
    log "WARN: rollout restart non-zero"

  rs_rc=0
  KUBECONFIG="$victim_kc" kubectl --context "$victim_ctx" -n "$deploy_ns" \
    rollout status "deployment/$deploy_name" --timeout="${probe_timeout}s" >/dev/null 2>&1 || rs_rc=$?
  restart_done_ns=$(date +%s%N)
  restart_duration_ms=$(( (restart_done_ns - restart_start_ns) / 1000000 ))

  post_gen=$(KUBECONFIG="$victim_kc" kubectl --context "$victim_ctx" -n "$deploy_ns" \
    get "deployment/$deploy_name" -o jsonpath='{.metadata.generation}' 2>/dev/null || echo 0)
  restart_ok=true
  if [ -z "$post_gen" ] || [ "$post_gen" -le "$pre_gen" ]; then
    log "iter=$iter: WARN Deployment generation did not advance (pre=$pre_gen post=$post_gen) — rollout may have been a no-op"
    restart_ok=false
  fi
  if [ "$rs_rc" -ne 0 ]; then
    log "iter=$iter: WARN rollout status returned rc=$rs_rc (likely timeout)"
    restart_ok=false
  fi
  emit "restart_complete" "{\"iter\":$iter,\"restart_done_ns\":$restart_done_ns,\"restart_duration_ms\":$restart_duration_ms,\"pre_gen\":$pre_gen,\"post_gen\":$post_gen,\"restart_ok\":$restart_ok}"

  # Post-settle (loop keeps running in pods)
  sleep "$post_settle_s"

  # Curl pods will finish on their own when loop_secs elapses. Collect
  # logs after they reach Succeeded/Failed.
  result_outdir=$(mktemp -d)
  collect_curl_logs "$iter" "$result_outdir" "${curl_pods[@]}"

  for entry in "${curl_pods[@]}"; do
    role="${entry%%:*}"
    emit_peer_survival "$iter" "$role" "$result_outdir/$role.csv" "$restart_start_ns" "$restart_done_ns" "$restart_duration_ms" "$restart_ok"
  done

  # Cleanup this iter's pods
  for entry in "${curl_pods[@]}"; do
    role="${entry%%:*}" pod="${entry##*:}"
    kc=$(jq -r --arg r "$role" '.[] | select(.role==$r) | .kubeconfig' "$clusters_json")
    ctx=$(jq -r --arg r "$role" '.[] | select(.role==$r) | .context // .name' "$clusters_json")
    KUBECONFIG="$kc" kubectl --context "$ctx" -n "$probe_ns" \
      delete pod "$pod" --grace-period=0 --force --wait=false >/dev/null 2>&1 || true
  done
  rm -rf "$result_outdir"

  if [ "$iter" -lt "$probe_count" ]; then
    sleep "$probe_interval"
  fi
done

log "DONE — exit_status=$exit_status"
