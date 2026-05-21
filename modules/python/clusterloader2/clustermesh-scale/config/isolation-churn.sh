#!/bin/bash
# Scenario #5 (Multi-Cluster Failure Isolation) — drives heavy pod-churn on
# ONLY the target cluster; peer clusters run a no-op observe path that
# sleeps for the same duration so their CL2 lifecycle (and Prometheus
# scrape window) covers the target's churn period.
#
# Why peer must sleep (not exit immediately): in share-infra mode, each
# scenario runs CL2 in parallel on every cluster. If peer exits the
# Method:Exec at t=0s, peer CL2 advances straight into settle + gather +
# teardown, finishing in ~3min — but target is still churning at t=10min.
# Peer Prometheus is torn down before target's churn finishes. To compare
# "did peers spike while target churned?" the peer Prometheus window must
# overlap target's churn window. Sleeping in this script keeps both
# lifecycles aligned.
#
# Positional args (all forwarded to pod-churn-killer.sh on target):
#   $1 TARGET_CONTEXT          kubectl context name of the cluster to churn.
#   $2 KILL_DURATION_SECONDS   Total kill-loop runtime on target (also peer sleep).
#   $3 KILL_INTERVAL_SECONDS   Seconds between kill rounds on target.
#   $4 KILL_BATCH              Pods deleted per round on target.
#   $5 WORKLOAD_GROUP          Label-selector group value for pod selection.
#
# Exit codes:
#   0 — always (target completes normally OR peer no-op observes for the
#   configured duration). Soft-fail matches the rest of Phase 4b's
#   scenario scripts so a single-cluster issue doesn't abort the run.

set -uo pipefail

TARGET_CONTEXT="${1:?target context required}"
KILL_DURATION_SECONDS="${2:-600}"
KILL_INTERVAL_SECONDS="${3:-10}"
KILL_BATCH="${4:-5}"
WORKLOAD_GROUP="${5:-clustermesh-isolation}"

# kubectl resolution: PATH first, then pre-staged binary (same pattern as
# apiserver-failure-killer.sh and pod-churn-killer.sh).
if command -v kubectl >/dev/null 2>&1; then
  KUBECTL=kubectl
elif [ -x /root/perf-tests/clusterloader2/config/kubectl ]; then
  KUBECTL=/root/perf-tests/clusterloader2/config/kubectl
  export PATH="/root/perf-tests/clusterloader2/config:${PATH}"
  echo "isolation-churn: using pre-staged kubectl at ${KUBECTL}"
else
  echo "isolation-churn ERROR: kubectl not in PATH and pre-staged binary missing"
  exit 127
fi

CURRENT_CONTEXT=$("${KUBECTL}" config current-context 2>/dev/null || echo "unknown")
echo "isolation-churn: current=${CURRENT_CONTEXT} target=${TARGET_CONTEXT}"

if [ "${CURRENT_CONTEXT}" != "${TARGET_CONTEXT}" ]; then
  echo "isolation-churn: peer cluster — observing for ${KILL_DURATION_SECONDS}s while target churns"
  sleep "${KILL_DURATION_SECONDS}"
  echo "isolation-churn: peer observation window complete"
  exit 0
fi

echo "isolation-churn: target cluster — delegating to pod-churn-killer.sh"
exec bash /root/perf-tests/clusterloader2/config/pod-churn-killer.sh \
  "${KILL_DURATION_SECONDS}" \
  "${KILL_INTERVAL_SECONDS}" \
  "${KILL_BATCH}" \
  "${WORKLOAD_GROUP}"
