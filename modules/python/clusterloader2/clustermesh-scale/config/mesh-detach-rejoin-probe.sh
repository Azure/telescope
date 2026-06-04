#!/usr/bin/env bash
# mesh-detach-rejoin-probe.sh
#
# cluster-loss-recovery scenario probe. Host-side orchestrator launched by
# execute.yml when CL2_DETACH_REJOIN_PROBE_ENABLED=true. Validates that
# Fleet's clustermeshprofile correctly detaches a cluster when its label no
# longer matches the selector, and re-attaches it on label restore.
#
# Phases (each with a hard wall-clock deadline so a slow-bleed failure
# can't wedge the entire run):
#
#   PRE-STATE  (60s) — assert all clusters at ready==total==(N-1) peers
#   DETACH     —     `az fleet member update --labels mesh=detaching` on victim
#                    `az fleet clustermeshprofile apply` (force reconcile)
#   WAIT-DETACH (300s) — poll remaining clusters; require ready==total==(N-2)
#                        on all of them. Captures time_to_detect_gone.
#   HOLD-N2    (60s) — steady-state observation; capture failure delta
#   REJOIN     —     `az fleet member update --labels mesh=true` on victim
#                    `az fleet clustermeshprofile apply`
#   WAIT-REJOIN (300s) — poll all clusters; require ready==total==(N-1).
#                        Captures time_to_rejoin_detect.
#   POST-STATE (60s) — final assert all at ready==total==(N-1)
#
# CRITICAL: an EXIT trap unconditionally restores mesh=true + applies CMP so
# a probe failure can't leave the mesh under-membered for downstream stages.
#
# Output: $REPORT_DIR/$ROLE-MeshDetachRejoinProbe.jsonl with one event per
# phase plus a summary row. scale.py _emit_detach_rejoin_probe_rows ingests.
#
# Required env (from execute.yml launch_mesh_detach_rejoin_probe):
#   CL2_DETACH_REJOIN_PROBE_ENABLED=true
#   CL2_FLEET_NAME, CL2_FLEET_RG, CL2_CMP_NAME, CL2_SUBSCRIPTION_ID
#   CLUSTERMESH_CLUSTERS_JSON (path to per-cluster name/role/kubeconfig array)
#   REPORT_DIR, SCENARIO_NAME, LEADER_ROLE
# Optional:
#   CL2_DETACH_REJOIN_VICTIM_ROLE — override deterministic max-role pick
#   CL2_DETACH_REJOIN_DETACH_TIMEOUT_S (default 300)
#   CL2_DETACH_REJOIN_REJOIN_TIMEOUT_S (default 300)
#   CL2_DETACH_REJOIN_HOLD_S          (default 60)

set -uo pipefail

readonly DEFAULT_DETACH_TIMEOUT=300
readonly DEFAULT_REJOIN_TIMEOUT=300
readonly DEFAULT_HOLD=60
readonly POLL_INTERVAL=10
# Bounded timeout for any single `az fleet` LRO call. Fleet LROs normally
# complete in 10-30s; 180s gives 6x margin without risking the script hanging
# until the AzDO job timeout if Fleet RP is wedged.
readonly AZ_CALL_TIMEOUT=180
readonly LABEL_KEY="${CL2_FLEET_LABEL_KEY:-mesh}"
readonly LABEL_VALUE_ATTACH="${CL2_FLEET_LABEL_VALUE:-true}"
readonly LABEL_VALUE_DETACH="${CL2_FLEET_LABEL_VALUE_DETACH:-detaching}"

detach_timeout="${CL2_DETACH_REJOIN_DETACH_TIMEOUT_S:-$DEFAULT_DETACH_TIMEOUT}"
rejoin_timeout="${CL2_DETACH_REJOIN_REJOIN_TIMEOUT_S:-$DEFAULT_REJOIN_TIMEOUT}"
hold_s="${CL2_DETACH_REJOIN_HOLD_S:-$DEFAULT_HOLD}"
# PRE-STATE timeout — sized after build 69300 evidence (60s was too short
# for n=3 first-convergence; LB allocation + CMP reconcile took >180s end
# to end). Defaults to detach timeout so a single tunable covers both.
pre_state_timeout="${CL2_DETACH_REJOIN_PRE_STATE_TIMEOUT_S:-$detach_timeout}"

log() { echo "[detach-rejoin-probe $(date -u +%H:%M:%S)] $*" >&2; }
fail_phase() { log "FAIL: $1"; exit_status="fail"; phase_fail="$2"; }

emit() {
  # emit phase-row JSONL to $report_jsonl
  # $1 = type
  # $2 (optional) = extra fields as JSON object string (default "{}")
  local _type="$1"
  # NOTE: ${2:-{}} parses as ${2:-{} + literal `}` in bash, which corrupts
  # set values by appending an extra `}`. Use explicit check instead.
  local _extra="${2:-}"
  [ -z "$_extra" ] && _extra='{}'
  printf '%s\n' "$(jq -nc \
    --arg type "$_type" \
    --arg scenario "${SCENARIO_NAME:-mesh-detach-rejoin-probe}" \
    --arg role "${LEADER_ROLE:-mesh-1}" \
    --arg victim "$victim_role" \
    --argjson n "$n_clusters" \
    --arg ts "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    --argjson extra "$_extra" \
    '{type:$type, scenario:$scenario, leader_role:$role, victim_role:$victim, n_clusters:$n, timestamp:$ts} * $extra' \
  )" >> "$report_jsonl"
}

# ---------- ARG PARSING + ENV VALIDATION ----------
report_dir="${REPORT_DIR:?REPORT_DIR required}"
scenario="${SCENARIO_NAME:-mesh-detach-rejoin-probe}"
leader_role="${LEADER_ROLE:-mesh-1}"
clusters_json="${CLUSTERMESH_CLUSTERS_JSON:?CLUSTERMESH_CLUSTERS_JSON required}"
fleet_name="${CL2_FLEET_NAME:?CL2_FLEET_NAME required}"
fleet_rg="${CL2_FLEET_RG:?CL2_FLEET_RG required}"
cmp_name="${CL2_CMP_NAME:?CL2_CMP_NAME required}"
sub_id="${CL2_SUBSCRIPTION_ID:?CL2_SUBSCRIPTION_ID required}"

mkdir -p "$report_dir"
report_jsonl="${report_dir}/${leader_role}-MeshDetachRejoinProbe.jsonl"
: > "$report_jsonl"

if [ ! -f "$clusters_json" ]; then
  log "ERROR: clusters json not found at $clusters_json"
  exit 1
fi

n_clusters=$(jq -r 'length' "$clusters_json")
if [ "$n_clusters" -lt 3 ]; then
  log "ERROR: need >=3 clusters for meaningful detach signal (got $n_clusters)"
  exit 1
fi

# Deterministic victim pick: max numeric role suffix (mesh-N where N highest)
victim_role="${CL2_DETACH_REJOIN_VICTIM_ROLE:-$(
  jq -r '[.[] | .role | capture("mesh-(?<n>[0-9]+)") | .n | tonumber] | max as $m | "mesh-\($m)"' "$clusters_json"
)}"

if ! jq -e --arg v "$victim_role" '[.[] | select(.role == $v)] | length > 0' "$clusters_json" >/dev/null; then
  log "ERROR: victim role $victim_role not found in clusters json"
  exit 1
fi

log "n_clusters=$n_clusters victim=$victim_role report=$report_jsonl"

exit_status="pass"
phase_fail=""
time_to_detect_gone_s="null"
time_to_rejoin_detect_s="null"
pre_failures="null"
post_failures="null"
cleanup_relabel_ok="null"
cleanup_apply_ok="null"

# ---------- CLEANUP TRAP (always restore mesh=true) ----------
cleanup() {
  local rc=$?
  log "cleanup: restoring $victim_role label to $LABEL_KEY=$LABEL_VALUE_ATTACH"
  if timeout "$AZ_CALL_TIMEOUT" az fleet member update \
    --subscription "$sub_id" --resource-group "$fleet_rg" \
    --fleet-name "$fleet_name" --name "$victim_role" \
    --labels "${LABEL_KEY}=${LABEL_VALUE_ATTACH}" \
    --output none 2>/dev/null; then
    cleanup_relabel_ok=true
  else
    cleanup_relabel_ok=false
    log "cleanup: relabel failed (already restored or Fleet RP wedged)"
  fi
  if timeout "$AZ_CALL_TIMEOUT" az fleet clustermeshprofile apply \
    --subscription "$sub_id" --resource-group "$fleet_rg" \
    --fleet-name "$fleet_name" --name "$cmp_name" \
    --output none 2>/dev/null; then
    cleanup_apply_ok=true
  else
    cleanup_apply_ok=false
    log "cleanup: CMP apply failed"
  fi
  emit "summary" "{
    \"exit_status\": \"$exit_status\",
    \"phase_fail\": \"$phase_fail\",
    \"time_to_detect_gone_s\": $time_to_detect_gone_s,
    \"time_to_rejoin_detect_s\": $time_to_rejoin_detect_s,
    \"pre_failures\": $pre_failures,
    \"post_failures\": $post_failures,
    \"detach_timeout_s\": $detach_timeout,
    \"rejoin_timeout_s\": $rejoin_timeout,
    \"cleanup_relabel_ok\": $cleanup_relabel_ok,
    \"cleanup_apply_ok\": $cleanup_apply_ok
  }"
  log "exit_status=$exit_status phase_fail=$phase_fail cleanup_relabel_ok=$cleanup_relabel_ok cleanup_apply_ok=$cleanup_apply_ok"
  exit $rc
}
trap cleanup EXIT

# ---------- HELPERS ----------
# Returns "ready/total" from cilium-dbg clustermesh status on a given cluster.
# Distroless-safe: uses cilium-dbg directly (no sh wrappers).
cm_status() {
  local _kc="$1" _ctx="$2"
  local _cil
  _cil=$(KUBECONFIG="$_kc" kubectl --context "$_ctx" -n kube-system get pods -l k8s-app=cilium -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)
  if [ -z "$_cil" ]; then echo "0/0"; return; fi
  KUBECONFIG="$_kc" kubectl --context "$_ctx" -n kube-system exec "$_cil" -c cilium-agent -- \
    cilium-dbg clustermesh status 2>/dev/null \
    | sed -nE 's/.*ClusterMesh:[[:space:]]+([0-9]+)\/([0-9]+) remote clusters ready.*/\1\/\2/p' \
    | head -1
}

# Sum of cilium_clustermesh_remote_cluster_failures sampled from one Cilium
# agent pod (mesh-1's first agent by jsonpath items[0]). Per-cluster sample,
# not cluster-wide — good enough for trend detection at n=3.
cm_failures_sample() {
  local _kc="$1" _ctx="$2"
  local _cil
  _cil=$(KUBECONFIG="$_kc" kubectl --context "$_ctx" -n kube-system get pods -l k8s-app=cilium -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)
  if [ -z "$_cil" ]; then echo "0"; return; fi
  KUBECONFIG="$_kc" kubectl --context "$_ctx" -n kube-system exec "$_cil" -c cilium-agent -- \
    cilium-dbg metrics list -o json 2>/dev/null \
    | jq -r '[.[] | select(.name=="cilium_clustermesh_remote_cluster_failures") | .value | tonumber] | add // 0'
}

# Wait until ALL clusters (or all non-victim if $3=true) report
# ready==total==$1. $2 = timeout seconds.
# Returns "OK ts_seen_first" or "TIMEOUT 0"
wait_peer_count() {
  local _expected="$1" _timeout="$2" _skip_victim="${3:-false}" _start_epoch
  _start_epoch=$(date +%s)
  local _seen_first=""
  while true; do
    local _now=$(date +%s)
    local _elapsed=$((_now - _start_epoch))
    if [ "$_elapsed" -gt "$_timeout" ]; then
      echo "TIMEOUT 0"
      return
    fi

    local all_match=true
    while IFS= read -r entry; do
      local role kc ctx
      role=$(echo "$entry" | jq -r '.role')
      kc=$(echo "$entry" | jq -r '.kubeconfig')
      # Use .context if present, fall back to .name (execute.yml currently
      # writes {name, rg, role, kubeconfig} without context; kubectl context
      # name == AKS cluster name == .name).
      ctx=$(echo "$entry" | jq -r '.context // .name')
      [ "$_skip_victim" = "true" ] && [ "$role" = "$victim_role" ] && continue

      local s; s=$(cm_status "$kc" "$ctx")
      [ -z "$s" ] && s="0/0"
      local ready=${s%/*} total=${s#*/}
      if [ "$ready" != "$_expected" ] || [ "$total" != "$_expected" ]; then
        all_match=false
      fi
    done < <(jq -c '.[]' "$clusters_json")

    if $all_match; then
      [ -z "$_seen_first" ] && _seen_first=$_elapsed
      echo "OK $_seen_first"
      return
    fi
    sleep "$POLL_INTERVAL"
  done
}

# ---------- PHASE 1: PRE-STATE ----------
log "Phase 1: PRE-STATE (assert ready==total==$((n_clusters - 1)) on ALL clusters incl. victim; deadline ${pre_state_timeout}s)"
pre_start=$(date +%s)
pre_result=$(wait_peer_count $((n_clusters - 1)) "$pre_state_timeout" false)
pre_status=${pre_result%% *}
pre_elapsed=${pre_result##* }
log "pre-state: $pre_result"
if [ "$pre_status" = "TIMEOUT" ]; then
  fail_phase "pre-state did not reach steady state within ${pre_state_timeout}s" "pre-state"
  exit 0
fi
emit "pre_state" "{\"pre_state_settle_s\": $pre_elapsed}"

# Capture pre-state failure count on observer (mesh-1 by convention)
mesh1_kc=$(jq -r '.[] | select(.role=="mesh-1") | .kubeconfig' "$clusters_json")
mesh1_ctx=$(jq -r '.[] | select(.role=="mesh-1") | .context // .name' "$clusters_json")
pre_failures=$(cm_failures_sample "$mesh1_kc" "$mesh1_ctx")
log "pre_failures (mesh-1 sample): $pre_failures"

# ---------- PHASE 2: DETACH ----------
log "Phase 2: DETACH ($victim_role label $LABEL_KEY=$LABEL_VALUE_DETACH)"
detach_start_ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)
detach_start_epoch=$(date +%s)
emit "detach_start" "{\"detach_start_ts\": \"$detach_start_ts\"}"

# Capture rc separately so `tee` doesn't mask az failure (set -o pipefail
# would also work but the explicit capture is more obvious in logs).
detach_az_rc=0
timeout "$AZ_CALL_TIMEOUT" az fleet member update \
  --subscription "$sub_id" --resource-group "$fleet_rg" \
  --fleet-name "$fleet_name" --name "$victim_role" \
  --labels "${LABEL_KEY}=${LABEL_VALUE_DETACH}" \
  --output none >> "${report_jsonl}.detach.log" 2>&1 || detach_az_rc=$?
if [ "$detach_az_rc" -ne 0 ]; then
  fail_phase "az fleet member update (detach) failed rc=$detach_az_rc" "detach-api"
  exit 0
fi

detach_apply_rc=0
timeout "$AZ_CALL_TIMEOUT" az fleet clustermeshprofile apply \
  --subscription "$sub_id" --resource-group "$fleet_rg" \
  --fleet-name "$fleet_name" --name "$cmp_name" \
  --output none >> "${report_jsonl}.detach.log" 2>&1 || detach_apply_rc=$?
if [ "$detach_apply_rc" -ne 0 ]; then
  fail_phase "az fleet clustermeshprofile apply (post-detach) failed rc=$detach_apply_rc" "detach-cmp-apply"
  exit 0
fi

# ---------- PHASE 3: WAIT-DETACH ----------
log "Phase 3: WAIT-DETACH (require ready==total==$((n_clusters - 2)) on N-1 observers, skip victim; deadline ${detach_timeout}s)"
detach_result=$(wait_peer_count $((n_clusters - 2)) "$detach_timeout" true)
detach_status=${detach_result%% *}
detach_elapsed=${detach_result##* }
log "wait-detach: $detach_result"
if [ "$detach_status" = "TIMEOUT" ]; then
  exit_status="partial"
  phase_fail="wait-detach"
  log "WARN: detach did not propagate within ${detach_timeout}s; skipping HOLD + going to REJOIN"
  emit "wait_detach_timeout" "{\"wait_detach_elapsed_s\": $detach_timeout}"
else
  time_to_detect_gone_s=$detach_elapsed
  emit "wait_detach_complete" "{\"time_to_detect_gone_s\": $detach_elapsed}"

  # ---------- PHASE 4: HOLD-N2 ----------
  log "Phase 4: HOLD-N2 ($hold_s seconds)"
  sleep "$hold_s"
  hold_failures=$(cm_failures_sample "$mesh1_kc" "$mesh1_ctx")
  emit "hold_n2_complete" "{\"hold_s\": $hold_s, \"hold_failures\": $hold_failures}"
fi

# ---------- PHASE 5: REJOIN ----------
log "Phase 5: REJOIN ($victim_role label $LABEL_KEY=$LABEL_VALUE_ATTACH)"
rejoin_start_ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)
rejoin_start_epoch=$(date +%s)
emit "rejoin_start" "{\"rejoin_start_ts\": \"$rejoin_start_ts\"}"

rejoin_az_rc=0
timeout "$AZ_CALL_TIMEOUT" az fleet member update \
  --subscription "$sub_id" --resource-group "$fleet_rg" \
  --fleet-name "$fleet_name" --name "$victim_role" \
  --labels "${LABEL_KEY}=${LABEL_VALUE_ATTACH}" \
  --output none >> "${report_jsonl}.rejoin.log" 2>&1 || rejoin_az_rc=$?
if [ "$rejoin_az_rc" -ne 0 ]; then
  fail_phase "az fleet member update (rejoin) failed rc=$rejoin_az_rc" "rejoin-api"
  exit 0
fi

rejoin_apply_rc=0
timeout "$AZ_CALL_TIMEOUT" az fleet clustermeshprofile apply \
  --subscription "$sub_id" --resource-group "$fleet_rg" \
  --fleet-name "$fleet_name" --name "$cmp_name" \
  --output none >> "${report_jsonl}.rejoin.log" 2>&1 || rejoin_apply_rc=$?
if [ "$rejoin_apply_rc" -ne 0 ]; then
  fail_phase "az fleet clustermeshprofile apply (post-rejoin) failed rc=$rejoin_apply_rc" "rejoin-cmp-apply"
  exit 0
fi

# ---------- PHASE 6: WAIT-REJOIN + POST-STATE ----------
log "Phase 6: WAIT-REJOIN (require ready==total==$((n_clusters - 1)) on ALL clusters incl. victim; deadline ${rejoin_timeout}s)"
rejoin_result=$(wait_peer_count $((n_clusters - 1)) "$rejoin_timeout" false)
rejoin_status=${rejoin_result%% *}
rejoin_elapsed=${rejoin_result##* }
log "wait-rejoin: $rejoin_result"
if [ "$rejoin_status" = "TIMEOUT" ]; then
  exit_status="partial"
  [ -z "$phase_fail" ] && phase_fail="wait-rejoin"
  emit "wait_rejoin_timeout" "{\"wait_rejoin_elapsed_s\": $rejoin_timeout}"
else
  time_to_rejoin_detect_s=$rejoin_elapsed
  emit "wait_rejoin_complete" "{\"time_to_rejoin_detect_s\": $rejoin_elapsed}"
  post_failures=$(cm_failures_sample "$mesh1_kc" "$mesh1_ctx")
  emit "post_state_complete" "{\"post_failures\": $post_failures}"
fi

log "DONE — exit_status=$exit_status"
