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
  "pre_kill_replicas": ${PRE_KILL_REPLICAS:-0},
  "ready_pods_at_kill": ${READY_PODS_AT_KILL:-0},
  "note": "${note}"
}
EOF
  echo "apiserver-failure-killer: wrote ${TIMING_FILE}"
}

# 1. Capture pre-kill state: ALL clustermesh-apiserver pods (name=uid=ready),
#    not just the first. With HA replicas>1 (scenario #7), the wait-for-new-pod
#    loop must distinguish "new replacement pod" from "the OTHER surviving
#    replicas that were already Ready before the kill" — a single-UID compare
#    matches the surviving pods immediately and falsely reports recovered=0s.
#    Rubber-duck critique blocker #2.
PRE_KILL_PODS=$("${KUBECTL}" -n kube-system get pods \
  -l k8s-app=clustermesh-apiserver \
  -o 'jsonpath={range .items[*]}{.metadata.name}={.metadata.uid}={.status.conditions[?(@.type=="Ready")].status}{"\n"}{end}' \
  2>/dev/null | grep -v '^$')

if [ -z "${PRE_KILL_PODS}" ]; then
  echo "apiserver-failure-killer ERROR: no clustermesh-apiserver pod matched label selector"
  PRE_KILL_REPLICAS=0
  READY_PODS_AT_KILL=0
  write_timing 0 0 false "" "" "" "no pod matched label selector k8s-app=clustermesh-apiserver"
  exit 1
fi

PRE_KILL_REPLICAS=$(echo "${PRE_KILL_PODS}" | wc -l | tr -d ' ')
READY_PODS_AT_KILL=$(echo "${PRE_KILL_PODS}" | awk -F'=' '$3=="True"{c++} END{print c+0}')
# Newline-separated list of pre-kill UIDs — used to filter the recovery
# wait loop's candidate set.
PRE_KILL_UIDS=$(echo "${PRE_KILL_PODS}" | awk -F'=' '{print $2}')

# Pick the first Ready pod as the kill target (preserves prior behavior for
# scenario #4). If no Ready pod, fall back to first pod.
TARGET_LINE=$(echo "${PRE_KILL_PODS}" | awk -F'=' '$3=="True"{print; exit}')
if [ -z "${TARGET_LINE}" ]; then
  TARGET_LINE=$(echo "${PRE_KILL_PODS}" | head -1)
fi
POD_NAME="${TARGET_LINE%%=*}"
_REST="${TARGET_LINE#*=}"
POD_UID="${_REST%=*}"
echo "apiserver-failure-killer: pre-kill replicas=${PRE_KILL_REPLICAS} ready=${READY_PODS_AT_KILL}"
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
#
# Periodic state samples (every 30s) write to a diag log so we can see
# what kubelet/scheduler/operator were doing during recovery — instead
# of just "timed out" with no signal.
DIAG_LOG="${REPORT_DIR}/ApiserverFailureDiag_${CURRENT_CONTEXT}.log"
: > "${DIAG_LOG}"

dump_state() {
  local label="$1"
  {
    echo "===== ${label} at $(date -u +"%Y-%m-%dT%H:%M:%SZ") (epoch=$(date +%s)) ====="
    echo "--- pods (k8s-app=clustermesh-apiserver) ---"
    "${KUBECTL}" -n kube-system get pods -l k8s-app=clustermesh-apiserver -o wide 2>&1 || true
    echo "--- pod UIDs + readiness ---"
    "${KUBECTL}" -n kube-system get pods -l k8s-app=clustermesh-apiserver \
      -o 'jsonpath={range .items[*]}{.metadata.name}{" uid="}{.metadata.uid}{" phase="}{.status.phase}{" ready="}{.status.conditions[?(@.type=="Ready")].status}{" reason="}{.status.conditions[?(@.type=="Ready")].reason}{"\n"}{end}' 2>&1 || true
    # tee'd to BOTH the file AND stdout so the AzDO step log carries the
    # same diag info as the file. AzDO pipeline artifacts aren't published
    # for our scenarios — the agent's report dir is torn down with the job
    # — so without stdout duplication the diag is unreachable.
  } 2>&1 | tee -a "${DIAG_LOG}"
}

RECOVERY_DEADLINE=$((T0 + RECOVERY_TIMEOUT_SECONDS))
NEW_POD_NAME=""
NEW_POD_UID=""
NEXT_SAMPLE=$((T0 + 30))
while [ "$(date +%s)" -lt "${RECOVERY_DEADLINE}" ]; do
  # Find any clustermesh-apiserver pod whose UID is NEW (not in the pre-kill
  # UID set) AND whose Ready condition is True.
  #
  # BUG-FIX 2026-05-13a: original kubectl jsonpath nested `[?]` filter is
  # broken — switched to shell-side filter listing all pods.
  #
  # BUG-FIX 2026-05-13b: original filter compared against a SINGLE killed-pod
  # UID. With HA replicas>1 (scenario #7), the surviving N-1 replicas already
  # have different UIDs and are Ready, so the filter would match one of them
  # instantly → false `recovered after 0s`. Rubber-duck critique blocker #2.
  # Fix: filter against the pre-kill UID set (every pod present at kill time),
  # so only a genuinely new replacement pod passes.
  ALL_PODS=$("${KUBECTL}" -n kube-system get pods \
    -l k8s-app=clustermesh-apiserver \
    -o 'jsonpath={range .items[*]}{.metadata.name}={.metadata.uid}={.status.conditions[?(@.type=="Ready")].status}{"\n"}{end}' \
    2>/dev/null | grep -v '^$' | grep '=True$')
  CANDIDATE=""
  if [ -n "${ALL_PODS}" ]; then
    while IFS= read -r _line; do
      [ -z "${_line}" ] && continue
      # _line format: name=uid=True
      _name_uid="${_line%=*}"          # name=uid
      _uid="${_name_uid#*=}"           # uid
      _in_set=0
      for _old_uid in ${PRE_KILL_UIDS}; do
        if [ "${_uid}" = "${_old_uid}" ]; then
          _in_set=1
          break
        fi
      done
      if [ "${_in_set}" -eq 0 ]; then
        CANDIDATE="${_line}"
        break
      fi
    done <<EOF
${ALL_PODS}
EOF
  fi
  if [ -n "${CANDIDATE}" ]; then
    NAME_UID="${CANDIDATE%=*}"
    NEW_POD_NAME="${NAME_UID%=*}"
    NEW_POD_UID="${NAME_UID#*=}"
    break
  fi
  # Periodic state sample for diagnostics.
  NOW=$(date +%s)
  if [ "${NOW}" -ge "${NEXT_SAMPLE}" ]; then
    dump_state "RECOVERY-WAIT sample (elapsed=$((NOW - T0))s)"
    NEXT_SAMPLE=$((NOW + 30))
  fi
  sleep 2
done

T1=$(date +%s)
if [ -z "${NEW_POD_UID}" ]; then
  echo "apiserver-failure-killer WARN: recovery timeout after ${RECOVERY_TIMEOUT_SECONDS}s; no NEW Ready pod"
  # Final diag dump on timeout — describe deployment, latest pod, recent events.
  # tee'd so AzDO step log AND the file both contain the diag (see dump_state
  # comment for why duplication matters).
  {
    echo "===== TIMEOUT FINAL DIAG at $(date -u +"%Y-%m-%dT%H:%M:%SZ") ====="
    echo "--- describe deployment clustermesh-apiserver ---"
    "${KUBECTL}" -n kube-system describe deployment clustermesh-apiserver 2>&1 || true
    echo "--- describe ALL clustermesh-apiserver pods ---"
    for p in $("${KUBECTL}" -n kube-system get pods -l k8s-app=clustermesh-apiserver -o name 2>/dev/null); do
      echo "--- $p ---"
      "${KUBECTL}" -n kube-system describe "$p" 2>&1 || true
    done
    echo "--- recent kube-system events ---"
    "${KUBECTL}" -n kube-system get events --sort-by=.lastTimestamp 2>&1 | tail -50 || true
  } 2>&1 | tee -a "${DIAG_LOG}"
  echo "apiserver-failure-killer: diag dump written to ${DIAG_LOG}"
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
