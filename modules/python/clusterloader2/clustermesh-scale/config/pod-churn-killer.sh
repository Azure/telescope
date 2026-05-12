#!/bin/bash
# Pod-churn killer loop — runs from inside the CL2 docker container
# (invoked via Method: Exec from pod-churn-combined.yaml).
#
# Why this lives here instead of as an in-cluster Job: the in-cluster Job
# approach requires pulling a kubectl image (e.g. bitnami/kubectl) onto
# every AKS cluster, which needs AcrPull or a public-registry-friendly
# CSSC-compliant image — neither is currently configured in the
# clustermesh-scale tfvars. The CL2 container already has the kubeconfig
# mounted at /root/.kube/config and (per Telescope's
# job_controller/config/ray/config.yaml precedent) supports `Method: Exec`
# with `bash`. We run kubectl from here against the same kubeconfig CL2
# uses — no extra image pull, no extra RBAC. Plan 4a runs this against
# one cluster per per-cluster CL2 instance (execute-parallel handles
# fan-out).
#
# Positional args (passed via Method: Exec command list):
#   $1 KILL_DURATION_SECONDS    Total runtime in seconds.
#   $2 KILL_INTERVAL_SECONDS    Seconds between successive kill rounds.
#   $3 KILL_BATCH               Pods deleted per round.
#   $4 WORKLOAD_GROUP           Label-selector group value.
#
# Exits 0 on successful completion of the time-bounded loop. Exits 127
# if kubectl is unavailable in this CL2 image (Method: Exec marks the
# measurement failed; the surrounding combined.yaml still completes the
# settle + gather steps so scale-phase data is preserved).

set -u
set -o pipefail

KILL_DURATION_SECONDS="${1:-600}"
KILL_INTERVAL_SECONDS="${2:-10}"
KILL_BATCH="${3:-5}"
WORKLOAD_GROUP="${4:-clustermesh-pod-churn}"
LABEL_SELECTOR="group=${WORKLOAD_GROUP}"

if ! command -v kubectl >/dev/null 2>&1; then
  echo "killer ERROR: kubectl not in PATH inside CL2 container; "\
       "falling back to in-cluster Job design required (see pod-churn-kill.yaml)"
  echo "killer ERROR: PATH=$PATH"
  exit 127
fi

KUBECTL_CLIENT_INFO="$(kubectl version --client=true --output=yaml 2>&1 | head -3 || true)"
echo "killer: kubectl client info:"
echo "${KUBECTL_CLIENT_INFO}"
echo "killer: starting (duration=${KILL_DURATION_SECONDS}s interval=${KILL_INTERVAL_SECONDS}s batch=${KILL_BATCH} selector=${LABEL_SELECTOR})"

# shuf is GNU coreutils; not guaranteed in every image base. Fall back to
# awk-with-srand when missing — awk is part of POSIX and always available.
HAS_SHUF=0
if command -v shuf >/dev/null 2>&1; then
  HAS_SHUF=1
fi

random_pick() {
  # Reads "ns/name" lines on stdin, prints up to $1 random lines.
  local n="$1"
  if [ "${HAS_SHUF}" -eq 1 ]; then
    shuf | head -n "$n"
  else
    awk -v n="$n" 'BEGIN{srand()} {print rand()" "$0}' | sort -k1,1n | head -n "$n" | cut -d" " -f2-
  fi
}

END_EPOCH=$(( $(date +%s) + KILL_DURATION_SECONDS ))
ROUND=0
KILLED_TOTAL=0

while [ "$(date +%s)" -lt "${END_EPOCH}" ]; do
  ROUND=$((ROUND + 1))

  CANDIDATES="$(kubectl get pods -A -l "${LABEL_SELECTOR}" \
    -o 'jsonpath={range .items[*]}{.metadata.namespace}/{.metadata.name}{"\n"}{end}' 2>/dev/null || true)"

  if [ -z "${CANDIDATES}" ]; then
    echo "killer: round=${ROUND} no candidates matched selector ${LABEL_SELECTOR}"
  else
    TARGETS="$(printf '%s\n' "${CANDIDATES}" | random_pick "${KILL_BATCH}")"
    ROUND_KILLED=0
    while IFS= read -r nsname; do
      [ -z "${nsname}" ] && continue
      ns="${nsname%%/*}"
      name="${nsname##*/}"
      # --grace-period=0 + --force: immediate evict, no graceful shutdown
      # wait. Simulates a "node failure"-style event for the pod-event
      # propagation path. --ignore-not-found tolerates the inherent race
      # where ReplicaSet has not yet replaced previous round's kills.
      if kubectl delete pod -n "${ns}" "${name}" \
            --grace-period=0 --force --ignore-not-found \
            > /dev/null 2>&1; then
        ROUND_KILLED=$((ROUND_KILLED + 1))
      fi
    done <<< "${TARGETS}"
    KILLED_TOTAL=$((KILLED_TOTAL + ROUND_KILLED))
    echo "killer: round=${ROUND} killed=${ROUND_KILLED} cumulative=${KILLED_TOTAL}"
  fi

  # Don't sleep past the deadline.
  NOW="$(date +%s)"
  REMAINING=$(( END_EPOCH - NOW ))
  if [ "${REMAINING}" -le 0 ]; then
    break
  fi
  SLEEP="${KILL_INTERVAL_SECONDS}"
  if [ "${REMAINING}" -lt "${SLEEP}" ]; then
    SLEEP="${REMAINING}"
  fi
  sleep "${SLEEP}"
done

echo "killer: done duration=${KILL_DURATION_SECONDS}s rounds=${ROUND} cumulative=${KILLED_TOTAL}"
exit 0
