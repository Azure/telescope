#!/bin/bash
# Scenario #4 (ClusterMesh APIServer Failure) — kills clustermesh-apiserver
# pod on the designated target cluster, then waits for the replacement pod
# to reach Ready. Records timestamps for post-hoc recovery-time analysis.
#
# Per-cluster CL2 execution model: this script runs from inside EVERY
# cluster's CL2 docker container, but no-ops on non-target clusters. The
# target is identified by `kubectl config current-context` — `az aks
# get-credentials` writes context = AKS cluster name (e.g. "clustermesh-1"),
# which matches what we pass as the target arg.
#
# Positional args:
#   $1 TARGET_CONTEXT             kubectl context name of the target cluster
#                                 (e.g. "clustermesh-1"). Skip if mismatched.
#   $2 RECOVERY_TIMEOUT_SECONDS   How long to wait for replacement pod Ready.
#   $3 REPORT_DIR                 (optional) Path inside the CL2 container
#                                 where the timing JSON is written. Defaults
#                                 to /root/perf-tests/clusterloader2/results.
#
# Output:
#   Writes $REPORT_DIR/ApiserverFailureTimings_<context>.json (target only).
#   scale.py collect reads this file and emits an ApiserverFailureRecoveryTiming
#   row into the aggregated JSONL.
#
# Exit codes:
#   0 — non-target (no-op) OR target with verified kill + recovery.
#   1 — target attempt failed somewhere (no pod matched, kubectl failed,
#       recovery timeout). Writes the timing file with `recovered:false`
#       so collect can still surface that the scenario was attempted.

set -uo pipefail

TARGET_CONTEXT="${1:-clustermesh-1}"
RECOVERY_TIMEOUT_SECONDS="${2:-120}"
REPORT_DIR="${3:-/root/perf-tests/clusterloader2/results}"

# Same fallback pattern as pod-churn-killer.sh — prefer PATH kubectl, fall
# back to the pre-staged binary at the bind-mounted config dir.
if command -v kubectl >/dev/null 2>&1; then
  KUBECTL=kubectl
elif [ -x /root/perf-tests/clusterloader2/config/kubectl ]; then
  KUBECTL=/root/perf-tests/clusterloader2/config/kubectl
  echo "apiserver-failure-killer: using pre-staged kubectl at ${KUBECTL}"
else
  echo "apiserver-failure-killer ERROR: kubectl not in PATH and pre-staged binary missing"
  exit 127
fi

CURRENT_CONTEXT=$("${KUBECTL}" config current-context 2>/dev/null || echo "unknown")
echo "apiserver-failure-killer: current=${CURRENT_CONTEXT} target=${TARGET_CONTEXT}"

if [ "${CURRENT_CONTEXT}" != "${TARGET_CONTEXT}" ]; then
  echo "apiserver-failure-killer: not target cluster, no-op"
  exit 0
fi

# ----- Target cluster path -----
mkdir -p "${REPORT_DIR}"
TIMING_FILE="${REPORT_DIR}/ApiserverFailureTimings_${CURRENT_CONTEXT}.json"

write_timing() {
  # Args: t0_epoch t1_epoch_or_zero recovered_flag pod_name pod_uid_old pod_uid_new note
  local t0="$1" t1="$2" recovered="$3" pod_name="$4" uid_old="$5" uid_new="$6" note="$7"
  local dur=0
  if [ "${t1}" -gt 0 ] && [ "${t0}" -gt 0 ]; then
    dur=$((t1 - t0))
  fi
  cat > "${TIMING_FILE}" <<EOF
{
  "target_context": "${CURRENT_CONTEXT}",
  "t0_kill_epoch": ${t0},
  "t1_recovered_epoch": ${t1},
  "recovery_duration_seconds": ${dur},
  "recovered": ${recovered},
  "killed_pod_name": "${pod_name}",
  "killed_pod_uid": "${uid_old}",
  "replacement_pod_uid": "${uid_new}",
  "note": "${note}"
}
EOF
  echo "apiserver-failure-killer: wrote ${TIMING_FILE}"
}

# 1. Capture pod name + UID BEFORE delete. Per rubber-duck blocker #5:
#    don't trust "any Running pod appeared after delete" as proof — verify
#    a NEW pod (different UID) actually came up after the kill timestamp.
TARGET_POD_JSON=$("${KUBECTL}" -n kube-system get pods \
  -l k8s-app=clustermesh-apiserver \
  -o 'jsonpath={range .items[*]}{.metadata.name}={.metadata.uid}{"\n"}{end}' \
  2>/dev/null | grep -v '^$' | head -1)

if [ -z "${TARGET_POD_JSON}" ]; then
  echo "apiserver-failure-killer ERROR: no clustermesh-apiserver pod matched label selector"
  write_timing 0 0 false "" "" "" "no pod matched label selector k8s-app=clustermesh-apiserver"
  exit 1
fi

POD_NAME="${TARGET_POD_JSON%=*}"
POD_UID="${TARGET_POD_JSON#*=}"
echo "apiserver-failure-killer: target pod ${POD_NAME} uid=${POD_UID}"

# 2. Delete exactly that pod by name (not by label selector — prevents
#    accidental multi-pod kill on future HA setups).
T0=$(date +%s)
echo "apiserver-failure-killer: t0=${T0} deleting pod ${POD_NAME} (hard kill, --grace-period=0 --force)"
if ! "${KUBECTL}" -n kube-system delete pod "${POD_NAME}" \
    --grace-period=0 --force >/dev/null 2>&1; then
  echo "apiserver-failure-killer ERROR: kubectl delete pod ${POD_NAME} failed"
  write_timing "${T0}" 0 false "${POD_NAME}" "${POD_UID}" "" "kubectl delete failed"
  exit 1
fi

# 3. Wait for replacement pod to reach Ready. Per rubber-duck #6:
#    Ready (not just Running) is what matters — apiserver may be Running
#    while still loading certs / unable to serve mesh traffic.
RECOVERY_DEADLINE=$((T0 + RECOVERY_TIMEOUT_SECONDS))
NEW_POD_NAME=""
NEW_POD_UID=""
while [ "$(date +%s)" -lt "${RECOVERY_DEADLINE}" ]; do
  # Find any clustermesh-apiserver pod whose UID is NEW (not the one we killed)
  # AND whose Ready condition is True.
  CANDIDATE=$("${KUBECTL}" -n kube-system get pods \
    -l k8s-app=clustermesh-apiserver \
    -o 'jsonpath={range .items[?(@.status.conditions[?(@.type=="Ready")].status=="True")]}{.metadata.name}={.metadata.uid}{"\n"}{end}' \
    2>/dev/null | grep -v '^$' | grep -v "=${POD_UID}$" | head -1)
  if [ -n "${CANDIDATE}" ]; then
    NEW_POD_NAME="${CANDIDATE%=*}"
    NEW_POD_UID="${CANDIDATE#*=}"
    break
  fi
  sleep 2
done

T1=$(date +%s)
if [ -z "${NEW_POD_UID}" ]; then
  echo "apiserver-failure-killer WARN: recovery timeout after ${RECOVERY_TIMEOUT_SECONDS}s; no NEW Ready pod"
  write_timing "${T0}" 0 false "${POD_NAME}" "${POD_UID}" "" "recovery timeout"
  # Phase 4b: exit 0 on timeout (NOT 1). The timing JSON with
  # `recovered:false` is the load-bearing signal that the scenario was
  # attempted but did not recover within budget — Kusto queries on
  # ApiserverFailureRecoveryTiming.recovered will flag this. Exiting 1
  # here would cascade-fail the CL2 step → execute.yml's overall_rc=1 →
  # share-infra step exits with SucceededWithIssues at worst, but
  # peer-cluster measurements (which DID gather data about the failure
  # event) would also be wasted. Soft-fail is correct: rubber-duck
  # critique #10 confirmed.
  exit 0
fi

DUR=$((T1 - T0))
echo "apiserver-failure-killer: recovered after ${DUR}s; new pod ${NEW_POD_NAME} uid=${NEW_POD_UID}"
write_timing "${T0}" "${T1}" true "${POD_NAME}" "${POD_UID}" "${NEW_POD_UID}" "ok"
exit 0
