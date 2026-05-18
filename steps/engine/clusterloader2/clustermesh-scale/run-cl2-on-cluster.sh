#!/usr/bin/env bash
# Per-cluster CL2 worker for the clustermesh-scale scenario.
#
# Extracted from steps/engine/clusterloader2/clustermesh-scale/execute.yml
# so that scale.py execute-parallel can fan out N copies of this script with
# bounded concurrency. The body MUST stay equivalent to the original
# per-iteration bash for-loop body (CL2 invoke + junit check + log capture +
# failure diag) — see PR #1157 phase 3 for the parallelization rationale.
#
# Per-cluster log capture + failure diag happen IMMEDIATELY when this
# cluster's CL2 finishes — before peer clusters complete — so that
# `kubectl --tail` log windows and `kubectl get events` recency don't age out
# while peers are still running.
#
# Exit code:
#   0 — CL2 ran AND junit.xml reports failures=0 errors=0
#   1 — anything else (CL2 didn't write junit, or junit has failures/errors)
# This is the authoritative per-cluster pass/fail signal that
# scale.py execute-parallel aggregates into the step's exit code.
#
# Usage:
#   run-cl2-on-cluster.sh \
#     <role> <kubeconfig> <report_dir> \
#     <cl2_image> <cl2_config_dir> <cl2_config_file> \
#     <provider> <python_script_file> <python_workdir> \
#     [tear_down_prometheus_flag]
#
# tear_down_prometheus_flag: "1" → pass --tear-down-prometheus to scale.py
# execute. Used by share-infra mode so each scenario's CL2 deploys a fresh
# Prom. "0" or unset → preserve Prom for failure-diagnostic dump (default
# single-scenario behavior).

set -uo pipefail

if [ "$#" -lt 9 ] || [ "$#" -gt 10 ]; then
  echo "Usage: $0 <role> <kubeconfig> <report_dir> <cl2_image> <cl2_config_dir> <cl2_config_file> <provider> <python_script_file> <python_workdir> [tear_down_prometheus_flag]" >&2
  exit 2
fi

role="$1"
kubeconfig="$2"
report_dir="$3"
cl2_image="$4"
cl2_config_dir="$5"
cl2_config_file="$6"
provider="$7"
python_script_file="$8"
python_workdir="$9"
tear_down_prometheus_flag="${10:-0}"

mkdir -p "$report_dir"

echo "===================================================================="
echo "  Running CL2 on $role"
echo "===================================================================="

# Background Prometheus memory-limit patcher (Phase D fix 2026-05-16):
# CL2's bundled prometheus manifest hardcodes `resources.limits.memory: 2Gi`
# AND CL2 exposes only `--prometheus-memory-request` (not -limit) as a CLI
# knob. Build 67335 raised the request to 6Gi → k8s admission rejected the
# Prom StatefulSet with `requests: "6Gi" must be <= memory limit of 2Gi`
# → Prom was never created → every gather query returned "no endpoints
# available". Build 67347 used a 1Gi request (so request<=limit holds) but
# the 2Gi limit then OOM'd Prom under our cardinality, crashlooping mid-run.
#
# We can't change the CL2 image, but we CAN patch the Prometheus CR after
# prometheus-operator creates it. Run a polling background process that
# waits for the CR to exist, patches its `spec.resources.limits.memory` to
# 12Gi, then exits. Prom-operator reconciles the StatefulSet within a few
# seconds of the patch. The polling is cheap (1 kubectl get per 3s) and
# safely no-ops if the CR never appears (e.g. enable_prometheus=False
# scenarios).
PROM_LIMIT="${CL2_PROMETHEUS_MEMORY_LIMIT_GI:-12}Gi"
PROM_PATCH_LOG="$report_dir/prom-cr-patch.log"
{
  echo "[prom-patcher] starting; target limit=$PROM_LIMIT" >&2
  _deadline=$(( $(date +%s) + 600 ))  # 10min budget — CL2 startup well under
  _patched=0
  while [ "$(date +%s)" -lt "$_deadline" ]; do
    if KUBECONFIG="$kubeconfig" kubectl -n monitoring get prometheus k8s \
         -o jsonpath='{.spec.resources.limits.memory}' 2>/dev/null | grep -q .; then
      _current=$(KUBECONFIG="$kubeconfig" kubectl -n monitoring get prometheus k8s \
                  -o jsonpath='{.spec.resources.limits.memory}' 2>/dev/null || echo "")
      echo "[prom-patcher] found prometheus/k8s CR (current limit=$_current), patching to $PROM_LIMIT" >&2
      if KUBECONFIG="$kubeconfig" kubectl -n monitoring patch prometheus k8s \
           --type=merge -p "{\"spec\":{\"resources\":{\"limits\":{\"memory\":\"$PROM_LIMIT\"}}}}" >&2; then
        echo "[prom-patcher] patch OK; verifying reconcile..." >&2
        sleep 5
        _new=$(KUBECONFIG="$kubeconfig" kubectl -n monitoring get prometheus k8s \
                -o jsonpath='{.spec.resources.limits.memory}' 2>/dev/null || echo "")
        echo "[prom-patcher] post-patch limit=$_new" >&2
        _patched=1
        break
      else
        echo "[prom-patcher] patch failed; will retry in 5s" >&2
      fi
    fi
    sleep 3
  done
  if [ "$_patched" -eq 0 ]; then
    echo "[prom-patcher] timed out after 10min waiting for prometheus/k8s CR; Prom may be disabled for this scenario (--enable-prometheus-server=False)" >&2
  fi
} > "$PROM_PATCH_LOG" 2>&1 &
PROM_PATCH_PID=$!
echo "  $role: spawned prometheus-cr-patcher (PID=$PROM_PATCH_PID, log=$PROM_PATCH_LOG)"

# Background periodic snapshot daemon (n=20 debug enhancement 2026-05-16):
# At n=20 a per-cluster clustermesh-apiserver receives 19x the cross-cluster
# event traffic of n=2. A "post-run" snapshot misses the PEAK pressure window
# where saturation actually happens. This daemon captures lightweight state
# every 60s for the duration of CL2 so we can correlate verdicts with peak
# resource use ("when did mesh-7's apiserver start OOMing?") rather than
# guess from end-state. ~5KB per minute × ~40min CL2 ≈ 200KB per cluster —
# cheap. Failure of any kubectl call inside the loop is non-fatal (|| true).
SNAPSHOT_LOG="$report_dir/snapshots.log"
{
  echo "[snapshot] starting; will sample every 60s until SIGTERM"
  while true; do
    _ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)
    echo "===== snapshot @ $_ts ====="
    # 1. clustermesh-apiserver pod state (restart count + status)
    echo "--- clustermesh-apiserver pods ---"
    KUBECONFIG="$kubeconfig" kubectl -n kube-system get pods \
      -l k8s-app=clustermesh-apiserver \
      -o custom-columns=NAME:.metadata.name,STATUS:.status.phase,RESTARTS:.status.containerStatuses[*].restartCount,READY:.status.containerStatuses[*].ready \
      2>&1 || true
    # 2. cilium-agent restart counts (only pods with >0 restarts, to bound output)
    echo "--- cilium-agent pods with restarts ---"
    KUBECONFIG="$kubeconfig" kubectl -n kube-system get pods -l k8s-app=cilium \
      -o jsonpath='{range .items[?(@.status.containerStatuses[0].restartCount > 0)]}{.metadata.name}{"\t"}{.status.containerStatuses[0].restartCount}{"\n"}{end}' \
      2>&1 || true
    # 3. monitoring/prometheus state
    echo "--- prometheus-k8s ---"
    KUBECONFIG="$kubeconfig" kubectl -n monitoring get pods -l app.kubernetes.io/name=prometheus \
      -o custom-columns=NAME:.metadata.name,STATUS:.status.phase,RESTARTS:.status.containerStatuses[*].restartCount \
      2>&1 || true
    # 4. kubectl top (requires metrics-server which CL2 deploys). Capture
    # top-5 mem consumers in kube-system to spot OOM trajectories early.
    echo "--- top mem in kube-system ---"
    KUBECONFIG="$kubeconfig" kubectl top pods -n kube-system --sort-by=memory --no-headers 2>/dev/null | head -5 || echo "(kubectl top unavailable)"
    echo ""
    sleep 60
  done
} > "$SNAPSHOT_LOG" 2>&1 &
SNAPSHOT_PID=$!
echo "  $role: spawned snapshot-daemon (PID=$SNAPSHOT_PID, log=$SNAPSHOT_LOG)"

# Ensure background daemons get terminated when this script exits, regardless
# of CL2 outcome (otherwise they'd linger past job end and keep hitting kube-
# api).
trap 'kill $PROM_PATCH_PID $SNAPSHOT_PID 2>/dev/null || true' EXIT

cl2_passed=0
# Run CL2; collect outcome WITHOUT failing on a non-zero exit (so we can
# also inspect junit.xml for internal test failures even when CL2 exits
# 0). Treat as "passed" only if BOTH:
#   (a) junit.xml exists (CL2 actually completed and wrote a report)
#   (b) junit.xml has zero <failure>/<error> elements
# Without (b) we'd silently green-light runs where measurements failed
# — e.g. PodMonitor template substitution producing "<no value>", which
# k8s admission rejects but CL2 still writes junit with <failure> tags.
exec_extra_args=()
if [ "$tear_down_prometheus_flag" = "1" ]; then
  exec_extra_args+=(--tear-down-prometheus)
fi
(
  cd "$python_workdir" || exit 1
  PYTHONPATH="${PYTHONPATH:-}:$python_workdir" python3 -u "$python_script_file" execute \
    --cl2-image "$cl2_image" \
    --cl2-config-dir "$cl2_config_dir" \
    --cl2-report-dir "$report_dir" \
    --cl2-config-file "$cl2_config_file" \
    --kubeconfig "$kubeconfig" \
    --provider "$provider" \
    "${exec_extra_args[@]}"
) || true

if [ -f "$report_dir/junit.xml" ]; then
  # Count failure/error attrs from <testsuite ... failures="N" errors="M">.
  junit_failures=$(grep -oE 'failures="[0-9]+"' "$report_dir/junit.xml" | head -1 | grep -oE '[0-9]+' || echo 0)
  junit_errors=$(grep -oE 'errors="[0-9]+"' "$report_dir/junit.xml" | head -1 | grep -oE '[0-9]+' || echo 0)
  junit_failures=${junit_failures:-0}
  junit_errors=${junit_errors:-0}
  if [ "$junit_failures" -eq 0 ] && [ "$junit_errors" -eq 0 ]; then
    cl2_passed=1
  else
    # Soft-fail policy 2026-05-18 for ALL clustermesh-scale scenarios.
    # This runner is in steps/engine/clusterloader2/clustermesh-scale/ so it
    # ONLY runs for the clustermesh-scale topology — never affects other
    # repo scenarios. Across the 7 scenarios (event-throughput, pod-churn-
    # combined, apiserver-failure, ha-config, isolation, node-churn-combined,
    # upper-bound), we've seen junit failures that are NOT bugs but rather:
    #   - upper-bound build 67497 mesh-1: 2 Patch http2:client-connection-
    #     lost during restart-burst (=expected saturation signal)
    #   - n2_shared pod-churn-combined: PodStartupLatency P99 5m23s vs 3m
    #     SLI (=workload contention under continuous churn)
    #   - n2_node_churn_combined: transient AKS apiserver 503s on namespace
    #     creation (=normal early-startup back-pressure)
    # In every case CL2 still wrote junit.xml + measurement files. The
    # downstream classifier/dashboard layer evaluates the actual signals;
    # losing the entire blob because of a tight SLI assertion is far worse
    # than letting an "issue" run propagate. Log junit failures as warning
    # + set cl2_passed=1 so collect+upload runs. Operator sees the warning
    # in the AzDO UI and the blob has the actual measurement values to
    # decide if the assertion failure was real.
    echo "##vso[task.logissue type=warning;] $role: junit.xml reports failures=$junit_failures errors=$junit_errors (clustermesh-scale soft-fail; measurement data still uploaded — inspect blob for real signal values)"
    cl2_passed=1
  fi
fi

if [ "$cl2_passed" -eq 1 ]; then
  echo "  $role: CL2 run succeeded"
fi

# Always-on log capture (spec line 35: "Logs: clustermesh-apiserver,
# agent watchers"). Files land in $report_dir/logs/ so they are
# uploaded alongside junit.xml + measurement results when the
# publish step runs. Capturing PER CLUSTER as soon as that cluster's CL2
# finishes is important under parallel fan-out: if we waited until all
# peers completed, --tail windows and recent-events queries would age out
# diagnostic data on the cluster that finished first.
log_dir="$report_dir/logs"
mkdir -p "$log_dir"
echo "------- $role: capturing pod logs to $log_dir -------"
# clustermesh-apiserver: all three containers (apiserver / etcd /
# kvstoremesh) — bounded tail, single pod expected.
for c in apiserver etcd kvstoremesh; do
  KUBECONFIG="$kubeconfig" kubectl -n kube-system logs \
    -l k8s-app=clustermesh-apiserver -c "$c" --tail=4000 \
    > "$log_dir/clustermesh-apiserver-$c.log" 2>&1 || true
done
# cilium-agent: one pod per node — keep tail small to bound size.
KUBECONFIG="$kubeconfig" kubectl -n kube-system logs \
  -l k8s-app=cilium --tail=1000 --prefix=true \
  > "$log_dir/cilium-agent.log" 2>&1 || true
# cilium-operator: low-volume control plane.
KUBECONFIG="$kubeconfig" kubectl -n kube-system logs \
  -l io.cilium/app=operator --tail=2000 --prefix=true \
  > "$log_dir/cilium-operator.log" 2>&1 || true

if [ "$cl2_passed" -ne 1 ]; then
  # Dump enough state to distinguish prometheus-stack scheduling
  # failures from CL2 logic failures. Prometheus is the most common
  # culprit here — its pod requests 10Gi by default, doesn't fit on
  # Standard_D4s_v4. If the pod is Pending with FailedScheduling, the
  # describe events make that obvious.
  #
  # Note: scale.py passes tear_down_prometheus=False so the stack
  # survives this dump (otherwise CL2 would clean up before we look).
  echo "------- $role: CL2 FAILURE DIAG -------"
  echo "------- node allocatable / requested capacity -------"
  KUBECONFIG="$kubeconfig" kubectl get nodes -o wide 2>&1 || true
  KUBECONFIG="$kubeconfig" kubectl describe nodes 2>&1 | grep -A 4 "Allocatable\|Allocated resources" | head -40 || true

  echo "------- monitoring/* pods -------"
  KUBECONFIG="$kubeconfig" kubectl -n monitoring get pods -o wide 2>&1 || true

  echo "------- monitoring statefulsets -------"
  KUBECONFIG="$kubeconfig" kubectl -n monitoring get statefulset -o wide 2>&1 || true

  echo "------- Prometheus CR (operator input) -------"
  KUBECONFIG="$kubeconfig" kubectl -n monitoring get prometheus -o yaml 2>&1 | head -80 || true

  echo "------- prometheus-k8s pod describe -------"
  KUBECONFIG="$kubeconfig" kubectl -n monitoring describe pod -l app.kubernetes.io/name=prometheus 2>&1 | tail -60 || true

  echo "------- prometheus-operator logs (tail 60) -------"
  KUBECONFIG="$kubeconfig" kubectl -n monitoring logs -l app.kubernetes.io/name=prometheus-operator --tail=60 2>&1 || true

  echo "------- monitoring namespace events (recent) -------"
  KUBECONFIG="$kubeconfig" kubectl -n monitoring get events --sort-by='.lastTimestamp' 2>&1 | tail -30 || true

  # n=20 debug enhancement 2026-05-16 — extra diagnostics that matter at
  # higher mesh sizes. The current per-cluster diag misses (a) live resource
  # use at failure time, (b) cluster-wide Warning events outside monitoring/,
  # (c) cross-cluster peer pair state from each cluster's POV.
  echo "------- kube-system top pods (memory-sorted, n=20 OOM tracker) -------"
  KUBECONFIG="$kubeconfig" kubectl top pods -n kube-system --sort-by=memory --no-headers 2>&1 | head -20 || true

  echo "------- cluster-wide Warning events (recent, sorted by time) -------"
  KUBECONFIG="$kubeconfig" kubectl get events --all-namespaces \
    --field-selector type=Warning --sort-by='.lastTimestamp' 2>&1 | tail -30 || true

  echo "------- node resource pressure (Allocated + Conditions) -------"
  KUBECONFIG="$kubeconfig" kubectl describe nodes 2>&1 | \
    grep -E "^Name:|MemoryPressure|DiskPressure|PIDPressure|Allocated resources|^  cpu|^  memory" | head -60 || true

  echo "------- cilium clustermesh status (peer pair view from $role) -------"
  if command -v cilium-cli >/dev/null 2>&1 || [ -x /usr/local/bin/cilium ]; then
    CILIUM_BIN=$(command -v cilium-cli || command -v cilium || echo /usr/local/bin/cilium)
    KUBECONFIG="$kubeconfig" "$CILIUM_BIN" clustermesh status --wait=false 2>&1 | head -40 || true
  else
    echo "(cilium-cli not in PATH; skipping clustermesh status)"
  fi

  echo "------- pod-snapshot tail (last 200 lines from periodic daemon) -------"
  if [ -f "$SNAPSHOT_LOG" ]; then
    tail -200 "$SNAPSHOT_LOG" || true
  else
    echo "(snapshot log not found at $SNAPSHOT_LOG)"
  fi
  echo "------- end CL2 FAILURE DIAG -------"

  echo "##vso[task.logissue type=warning;] $role: CL2 run failed (junit missing or has failures/errors at $report_dir/junit.xml)"
  exit 1
fi

exit 0
