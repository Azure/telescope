#!/bin/bash
# upper-bound-label-churner.sh
#
# Scenario #6 (Upper Bound / Saturation Testing) — Phase B workload driver.
# Drives ClusterMesh identity-propagation events at a controllable, sustained
# rate by flipping a single label on existing workload pods. Each label flip
# triggers Cilium to recompute the pod's identity, which propagates as a
# kvstore event through the mesh.
#
# This pattern is favored over the original Phase A approach (rolling-restart
# bursts of the workload Deployments) because:
#
# 1. **Low cardinality** — same pods, same IPs, same series; Prometheus
#    doesn't accumulate new time-series per "event". The Phase A restart
#    workload exploded cAdvisor pod metric cardinality (new pod names per
#    restart) and OOM'd Prometheus before saturation criteria tripped on
#    the SUT (ClusterMesh). Builds 67224/67279/67300 all hit that
#    Prom-OOM monitoring-saturation point.
#
# 2. **Cilium-relevant** — label change → identity recompute → kvstore
#    event with scope=identities/v1 + ip/v1 (endpoint re-keyed by new
#    identity). Same primary signal Phase A wanted to drive, generated
#    cleanly without side-effecting Prom cardinality.
#
# 3. **Predictable rate** — script loops at exactly ops_per_sec rate.
#    Phase A restart-bursts didn't actually drive ops_per_sec linearly
#    because Deployment rolling restart is bounded by maxSurge (25% =
#    50 pods/wave on 200-pod workload). Restart count was the lever but
#    its mapping to events/sec was unclear.
#
# Args (positional):
#   $1  TARGET_CONTEXT       kubectl context to target (e.g. clustermesh-1)
#   $2  OPS_PER_SECOND       target rate of label flips (e.g. 100)
#   $3  DURATION_SECONDS     how long to run (e.g. 240)
#   $4  NAMESPACE_PREFIX     pod-source namespace prefix (e.g. clustermesh-ub)
#   $5  NAMESPACE_COUNT      number of namespaces to draw pods from (e.g. 5)
#   $6  TIMING_OUTPUT_PATH   path to write LabelChurnTimings_<context>.json
#                            (typically <report_dir>/LabelChurnTimings_<ctx>.json)
#
# Output (TIMING_OUTPUT_PATH, JSON):
#   {
#     "target_context": str,
#     "target_ops_per_second": int,
#     "duration_seconds": int,
#     "started_epoch": int,
#     "ended_epoch": int,
#     "ops_attempted": int,
#     "ops_succeeded": int,
#     "ops_failed": int,
#     "actual_ops_per_second": float,
#     "first_error": str   // empty on clean run
#   }
#
# Bash-portable, no jq/python dependencies inside the CL2 container.
# kubectl is pre-staged at $CL2_CONFIG_DIR/kubectl (see execute.yml's
# kubectl pre-stage block) and the kubeconfig is mounted at /root/.kube/
# config. Method:Exec runs this script with that context.
#
# Termination semantics: script runs for DURATION_SECONDS WALL CLOCK, then
# exits 0 regardless of how many ops succeeded. If kubectl fails repeatedly
# the script keeps trying (no fail-fast) since the saturation criterion is
# observable BY the failure rate; the classifier examines the rate of mesh
# failures + observed event rate to assign a verdict.

set -uo pipefail

# Phase B Method:Exec runs this script with kubeconfig mounted at
# /root/.kube/config. The current-context in that kubeconfig IS the
# target cluster (CL2 spawns one invocation per cluster). We default
# TARGET_CONTEXT to whatever current-context returns; pipeline matrix
# entries can still pass an explicit override if they want.
TARGET_CONTEXT="${1:-}"
OPS_PER_SECOND="${2:?OPS_PER_SECOND required}"
DURATION_SECONDS="${3:?DURATION_SECONDS required}"
NAMESPACE_PREFIX="${4:?NAMESPACE_PREFIX required}"
NAMESPACE_COUNT="${5:?NAMESPACE_COUNT required}"
TIMING_OUTPUT="${6:?TIMING_OUTPUT_PATH required}"

if [ "$OPS_PER_SECOND" -lt 0 ]; then
  echo "FATAL: OPS_PER_SECOND must be >= 0" >&2
  exit 2
fi
# OPS_PER_SECOND=0 → no-op skip path. Useful for keeping a rung's label-churn
# disabled while still running restart-bursts (Phase A compat mode). Sleeps
# for DURATION_SECONDS so the rung's measurement window stays correctly
# sized, then emits zero-ops timing JSON. This path deliberately runs BEFORE
# kubectl resolution / kubeconfig probing so that "ops=0" rungs cannot fail
# on environment issues — a 0-rate request must always be a clean no-op.
if [ "$OPS_PER_SECOND" -eq 0 ]; then
  echo "[label-churner] OPS_PER_SECOND=0 → no-op skip path, sleeping ${DURATION_SECONDS}s" >&2
  STARTED_EPOCH=$(date +%s)
  sleep "$DURATION_SECONDS"
  ENDED_EPOCH=$(date +%s)
  cat > "$TIMING_OUTPUT" <<EOF
{
  "target_context": "${TARGET_CONTEXT:-unset}",
  "target_ops_per_second": 0,
  "duration_seconds": $DURATION_SECONDS,
  "started_epoch": $STARTED_EPOCH,
  "ended_epoch": $ENDED_EPOCH,
  "ops_attempted": 0,
  "ops_succeeded": 0,
  "ops_failed": 0,
  "actual_ops_per_second": 0,
  "first_error": ""
}
EOF
  echo "[label-churner] wrote no-op timing file: $TIMING_OUTPUT" >&2
  exit 0
fi

# Resolve kubectl. Method:Exec mounts CL2's config dir at
# /root/perf-tests/clusterloader2/config; the pre-staged kubectl from
# execute.yml lives there.
KUBECTL=""
for candidate in /root/perf-tests/clusterloader2/config/kubectl /usr/local/bin/kubectl /usr/bin/kubectl kubectl; do
  if command -v "$candidate" >/dev/null 2>&1 || [ -x "$candidate" ]; then
    KUBECTL="$candidate"
    break
  fi
done
if [ -z "$KUBECTL" ]; then
  echo "FATAL: kubectl not found in PATH or /root/perf-tests/clusterloader2/config/" >&2
  exit 127
fi

# If TARGET_CONTEXT is empty, looks like an un-substituted shell expression
# ($(...) literal), or anything resembling "ContextNotResolved", fall back
# to kubectl config current-context. The CL2 docker container has
# /root/.kube/config mounted with the cluster's kubeconfig; current-context
# is set by `az aks get-credentials` upstream of CL2.
if [ -z "$TARGET_CONTEXT" ] || [[ "$TARGET_CONTEXT" == *'$('*  ]] || [[ "$TARGET_CONTEXT" == "auto" ]]; then
  TARGET_CONTEXT=$("$KUBECTL" --kubeconfig /root/.kube/config config current-context 2>/dev/null || echo "")
  if [ -z "$TARGET_CONTEXT" ]; then
    echo "FATAL: TARGET_CONTEXT empty and kubectl config current-context failed" >&2
    exit 2
  fi
  echo "[label-churner] auto-resolved TARGET_CONTEXT=$TARGET_CONTEXT from kubeconfig" >&2
fi

echo "[label-churner] using kubectl=$KUBECTL context=$TARGET_CONTEXT ops/s=$OPS_PER_SECOND duration=${DURATION_SECONDS}s" >&2

# Compute inter-op sleep budget. sleep_ns = 1_000_000_000 / ops_per_second.
# At very high rates kubectl latency itself becomes the bottleneck (kubectl
# ops take 10-50ms). For rates above ~50/s the actual rate will be
# kubectl-bound, not sleep-bound; we still issue ops as fast as possible
# and record what we achieved.
# nanoseconds per op = 1e9 / ops_per_second. Use bash arithmetic up to 1e9.
INTERVAL_NS=$((1000000000 / OPS_PER_SECOND))
echo "[label-churner] inter-op interval = ${INTERVAL_NS}ns (target rate $OPS_PER_SECOND ops/s)" >&2

# Build pod list once at start. Picking from a pool ensures we don't keep
# label-churning the same pod (which would be a no-op after the first flip
# in the same direction). All workload pods from the upper-bound namespaces
# are eligible.
echo "[label-churner] discovering target pods across $NAMESPACE_COUNT namespaces with prefix $NAMESPACE_PREFIX..." >&2
POD_LIST=""
for i in $(seq 1 "$NAMESPACE_COUNT"); do
  NS="${NAMESPACE_PREFIX}-${i}"
  PODS=$("$KUBECTL" --context "$TARGET_CONTEXT" -n "$NS" get pods \
    -o jsonpath='{range .items[?(@.status.phase=="Running")]}{.metadata.namespace} {.metadata.name}{"\n"}{end}' 2>/dev/null || echo "")
  POD_LIST="${POD_LIST}${PODS}"
done
POD_COUNT=$(echo -n "$POD_LIST" | grep -c '^[^[:space:]]' || true)
if [ "$POD_COUNT" -lt 1 ]; then
  echo "FATAL: no Running pods found in ${NAMESPACE_PREFIX}-{1..${NAMESPACE_COUNT}}; cannot churn" >&2
  # Still emit a timing file so the collector can detect the abort
  cat > "$TIMING_OUTPUT" <<EOF
{
  "target_context": "$TARGET_CONTEXT",
  "target_ops_per_second": $OPS_PER_SECOND,
  "duration_seconds": $DURATION_SECONDS,
  "started_epoch": $(date +%s),
  "ended_epoch": $(date +%s),
  "ops_attempted": 0,
  "ops_succeeded": 0,
  "ops_failed": 0,
  "actual_ops_per_second": 0,
  "first_error": "no Running pods found in target namespaces"
}
EOF
  exit 0
fi
echo "[label-churner] found $POD_COUNT pods to churn" >&2

# Read pod list into a bash array (whitespace-separated <ns> <name> pairs).
# Use mapfile for efficiency; fall back to a while-read loop on older bash.
POD_NS=()
POD_NAME=()
while read -r ns name; do
  [ -z "$ns" ] && continue
  POD_NS+=("$ns")
  POD_NAME+=("$name")
done <<< "$POD_LIST"

POD_COUNT=${#POD_NS[@]}
echo "[label-churner] loaded $POD_COUNT pod entries" >&2

# Stats
STARTED_EPOCH=$(date +%s)
END_EPOCH=$((STARTED_EPOCH + DURATION_SECONDS))
OPS_ATTEMPTED=0
OPS_SUCCEEDED=0
OPS_FAILED=0
FIRST_ERROR=""

# Per-op UNIQUE label value (Phase B rev2, rubber-duck fix 2026-05-15):
# original a|b toggle was a no-op once each pod had been visited twice with
# the same parity (e.g., on round-robin, pod0 always got 'a' on every odd
# visit). Identity recompute requires the LABEL VALUE TO ACTUALLY CHANGE
# from the pod's current value. We now use a monotonically increasing
# value (`v<OPS_ATTEMPTED>`) so every kubectl label op writes a value the
# target pod has never had → guaranteed identity recompute → guaranteed
# kvstore event. Old identities drop to refcount 0 once all pods that
# held them have moved on → Cilium identity GC reclaims, exercising the
# create/delete identity path that's central to ClusterMesh propagation.
LABEL_COUNTER=0

# Periodic progress (every ~5s wall clock) tracked via NEXT_LOG_EPOCH so
# the cadence holds even when kubectl latency throttles the actual rate
# below target (otherwise the prior "modulo OPS_ATTEMPTED" logic would
# never fire at low achieved rates).
NEXT_LOG_EPOCH=$((STARTED_EPOCH + 5))

# TERM/INT trap: if CL2's Method:Exec times out and SIGTERMs the script,
# still emit a partial timing file so collect's label_churn block records
# whatever we managed. Mark the run as truncated via first_error.
_emit_timing_and_exit() {
  local _signal="$1"
  local ENDED_EPOCH ELAPSED_S ACTUAL_RATE ESCAPED_ERR
  ENDED_EPOCH=$(date +%s)
  ELAPSED_S=$((ENDED_EPOCH - STARTED_EPOCH))
  if [ "$ELAPSED_S" -lt 1 ]; then ELAPSED_S=1; fi
  ACTUAL_RATE=$(awk -v s="$OPS_SUCCEEDED" -v e="$ELAPSED_S" 'BEGIN{printf "%.3f", s/e}')
  local _err="$FIRST_ERROR"
  if [ -n "$_signal" ]; then
    if [ -n "$_err" ]; then
      _err="signal=${_signal}; ${_err}"
    else
      _err="signal=${_signal} (label-churner truncated by CL2 timeout)"
    fi
  fi
  ESCAPED_ERR=$(printf '%s' "$_err" | sed 's/\\/\\\\/g; s/"/\\"/g; s/\t/\\t/g' | tr -d '\n')
  cat > "$TIMING_OUTPUT" <<EOF
{
  "target_context": "$TARGET_CONTEXT",
  "target_ops_per_second": $OPS_PER_SECOND,
  "duration_seconds": $DURATION_SECONDS,
  "started_epoch": $STARTED_EPOCH,
  "ended_epoch": $ENDED_EPOCH,
  "ops_attempted": $OPS_ATTEMPTED,
  "ops_succeeded": $OPS_SUCCEEDED,
  "ops_failed": $OPS_FAILED,
  "actual_ops_per_second": $ACTUAL_RATE,
  "first_error": "$ESCAPED_ERR"
}
EOF
  echo "[label-churner] wrote timing file: $TIMING_OUTPUT (signal=$_signal)" >&2
  exit 0
}
trap '_emit_timing_and_exit TERM' TERM
trap '_emit_timing_and_exit INT'  INT

# Inner loop: pick pod (round-robin), flip label, sleep INTERVAL_NS - elapsed.
# Track elapsed nanoseconds to drift-correct (so a series of slow kubectl
# calls doesn't permanently fall behind the target rate; we just don't sleep
# between ops when behind schedule).
NEXT_OP_NS=$(date +%s%N)
POD_IDX=0

while [ "$(date +%s)" -lt "$END_EPOCH" ]; do
  NS="${POD_NS[$POD_IDX]}"
  NAME="${POD_NAME[$POD_IDX]}"
  # Always-unique value (monotonic counter) so every op produces an
  # actual label-value change on the target pod → guaranteed Cilium
  # identity recompute → guaranteed kvstore event.
  LABEL_COUNTER=$((LABEL_COUNTER + 1))
  LABEL_VALUE="v${LABEL_COUNTER}"
  OPS_ATTEMPTED=$((OPS_ATTEMPTED + 1))

  if "$KUBECTL" --context "$TARGET_CONTEXT" -n "$NS" label pod "$NAME" \
      "ub-churn-tag=$LABEL_VALUE" --overwrite=true \
      --request-timeout=5s >/dev/null 2>&1; then
    OPS_SUCCEEDED=$((OPS_SUCCEEDED + 1))
  else
    OPS_FAILED=$((OPS_FAILED + 1))
    if [ -z "$FIRST_ERROR" ]; then
      FIRST_ERROR="kubectl label failed on ${NS}/${NAME}"
    fi
  fi

  # Round-robin pod index.
  POD_IDX=$(( (POD_IDX + 1) % POD_COUNT ))

  # Drift-correct sleep. NEXT_OP_NS advances by INTERVAL_NS each iter.
  NEXT_OP_NS=$((NEXT_OP_NS + INTERVAL_NS))
  NOW_NS=$(date +%s%N)
  DELTA_NS=$((NEXT_OP_NS - NOW_NS))
  if [ "$DELTA_NS" -gt 0 ]; then
    DELTA_S=$(awk -v ns="$DELTA_NS" 'BEGIN{printf "%.6f", ns/1e9}')
    sleep "$DELTA_S"
  fi
  # If DELTA_NS <= 0 we're behind schedule; don't sleep, charge ahead.

  # Wall-clock-based progress (every ~5s) so the log fires even when
  # actual rate is far below target (kubectl-bound at high rungs).
  NOW=$(date +%s)
  if [ "$NOW" -ge "$NEXT_LOG_EPOCH" ]; then
    ELAPSED=$((NOW - STARTED_EPOCH))
    REMAINING=$((END_EPOCH - NOW))
    if [ "$ELAPSED" -gt 0 ]; then
      ACTUAL_RATE=$(awk -v s="$OPS_SUCCEEDED" -v e="$ELAPSED" 'BEGIN{printf "%.1f", s/e}')
    else
      ACTUAL_RATE="0.0"
    fi
    echo "[label-churner] t+${ELAPSED}s: attempted=$OPS_ATTEMPTED succeeded=$OPS_SUCCEEDED failed=$OPS_FAILED actual_rate=${ACTUAL_RATE}/s remaining=${REMAINING}s" >&2
    NEXT_LOG_EPOCH=$((NOW + 5))
  fi
done

ENDED_EPOCH=$(date +%s)
ELAPSED_S=$((ENDED_EPOCH - STARTED_EPOCH))
if [ "$ELAPSED_S" -lt 1 ]; then ELAPSED_S=1; fi
ACTUAL_OPS_PER_SECOND=$(awk -v s="$OPS_SUCCEEDED" -v e="$ELAPSED_S" 'BEGIN{printf "%.3f", s/e}')

echo "[label-churner] FINAL: attempted=$OPS_ATTEMPTED succeeded=$OPS_SUCCEEDED failed=$OPS_FAILED actual_rate=${ACTUAL_OPS_PER_SECOND}/s over ${ELAPSED_S}s" >&2

# Emit timing JSON. Escape FIRST_ERROR's quotes/backslashes/newlines for JSON safety.
ESCAPED_ERR=$(printf '%s' "$FIRST_ERROR" | sed 's/\\/\\\\/g; s/"/\\"/g; s/\t/\\t/g' | tr -d '\n')

# Clear traps so the success-path output isn't re-emitted by _emit_timing_and_exit.
trap - TERM INT

cat > "$TIMING_OUTPUT" <<EOF
{
  "target_context": "$TARGET_CONTEXT",
  "target_ops_per_second": $OPS_PER_SECOND,
  "duration_seconds": $DURATION_SECONDS,
  "started_epoch": $STARTED_EPOCH,
  "ended_epoch": $ENDED_EPOCH,
  "ops_attempted": $OPS_ATTEMPTED,
  "ops_succeeded": $OPS_SUCCEEDED,
  "ops_failed": $OPS_FAILED,
  "actual_ops_per_second": $ACTUAL_OPS_PER_SECOND,
  "first_error": "$ESCAPED_ERR"
}
EOF

echo "[label-churner] wrote timing file: $TIMING_OUTPUT" >&2
exit 0
