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
#     <provider> <python_script_file> <python_workdir>

set -uo pipefail

if [ "$#" -ne 9 ]; then
  echo "Usage: $0 <role> <kubeconfig> <report_dir> <cl2_image> <cl2_config_dir> <cl2_config_file> <provider> <python_script_file> <python_workdir>" >&2
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

mkdir -p "$report_dir"

echo "===================================================================="
echo "  Running CL2 on $role"
echo "===================================================================="

cl2_passed=0
# Run CL2; collect outcome WITHOUT failing on a non-zero exit (so we can
# also inspect junit.xml for internal test failures even when CL2 exits
# 0). Treat as "passed" only if BOTH:
#   (a) junit.xml exists (CL2 actually completed and wrote a report)
#   (b) junit.xml has zero <failure>/<error> elements
# Without (b) we'd silently green-light runs where measurements failed
# — e.g. PodMonitor template substitution producing "<no value>", which
# k8s admission rejects but CL2 still writes junit with <failure> tags.
(
  cd "$python_workdir" || exit 1
  PYTHONPATH="${PYTHONPATH:-}:$python_workdir" python3 -u "$python_script_file" execute \
    --cl2-image "$cl2_image" \
    --cl2-config-dir "$cl2_config_dir" \
    --cl2-report-dir "$report_dir" \
    --cl2-config-file "$cl2_config_file" \
    --kubeconfig "$kubeconfig" \
    --provider "$provider"
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
    echo "##vso[task.logissue type=warning;] $role: junit.xml reports failures=$junit_failures errors=$junit_errors"
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
  echo "------- end CL2 FAILURE DIAG -------"

  echo "##vso[task.logissue type=warning;] $role: CL2 run failed (junit missing or has failures/errors at $report_dir/junit.xml)"
  exit 1
fi

exit 0
