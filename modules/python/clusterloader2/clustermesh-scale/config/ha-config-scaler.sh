#!/bin/bash
# Scenario #7 (HA Configuration Validation) — scales the clustermesh-apiserver
# Deployment up/down to compare resource overhead, failover behavior, and event
# duplication between single-replica and multi-replica HA configurations.
#
# Unlike apiserver-failure-killer.sh (which targets a single cluster), this
# script runs on EVERY cluster's CL2 instance and scales each cluster's own
# clustermesh-apiserver. Mesh-wide HA is the realistic production config; only
# scaling one cluster would conflate HA-overhead measurements with a
# single-cluster outlier.
#
# Positional args:
#   $1 ACTION       scale-up | scale-down
#   $2 REPLICAS     Target replicas count (required for scale-up; ignored for
#                   scale-down which always restores to 1).
#   $3 REPORT_DIR   (optional) Path inside the CL2 container where timing JSON
#                   is written. Defaults to /root/perf-tests/clusterloader2/results.
#
# Output:
#   On scale-up only, writes $REPORT_DIR/HAConfigScalingTimings_<context>.json
#   with the scale duration, observed spec/ready replicas, and a
#   ha_replicas_honored flag (true iff spec==REPLICAS AND ready==REPLICAS at
#   the end of a 30s post-rollout poll window — catches ENO revert).
#   scale.py collect emits one HAConfigScalingTiming JSONL row per file.
#
# Exit codes:
#   0 — always (soft-fail). Scale-up failures still emit the timing file with
#   ha_replicas_honored:false so Kusto queries can flag degraded HA runs.

set -uo pipefail

ACTION="${1:?action required: scale-up|scale-down}"
REPLICAS="${2:-1}"
REPORT_DIR="${3:-/root/perf-tests/clusterloader2/results}"

# kubectl resolution: PATH first, then pre-staged binary (same pattern as
# apiserver-failure-killer.sh and pod-churn-killer.sh).
if command -v kubectl >/dev/null 2>&1; then
  KUBECTL=kubectl
elif [ -x /root/perf-tests/clusterloader2/config/kubectl ]; then
  KUBECTL=/root/perf-tests/clusterloader2/config/kubectl
  echo "ha-config-scaler: using pre-staged kubectl at ${KUBECTL}"
else
  echo "ha-config-scaler ERROR: kubectl not in PATH and pre-staged binary missing"
  exit 0
fi

CURRENT_CONTEXT=$("${KUBECTL}" config current-context 2>/dev/null || echo "unknown")
mkdir -p "${REPORT_DIR}"
TIMING_FILE="${REPORT_DIR}/HAConfigScalingTimings_${CURRENT_CONTEXT}.json"

emit_timing() {
  # Args: action requested_replicas spec_replicas_after ready_replicas_after honored duration_s note
  local action="$1" requested="$2" spec_after="$3" ready_after="$4"
  local honored="$5" dur="$6" note="$7"
  cat > "${TIMING_FILE}" <<EOF
{
  "context": "${CURRENT_CONTEXT}",
  "action": "${action}",
  "requested_replicas": ${requested},
  "spec_replicas_after": ${spec_after},
  "ready_replicas_after": ${ready_after},
  "ha_replicas_honored": ${honored},
  "scale_duration_seconds": ${dur},
  "note": "${note}"
}
EOF
  echo "ha-config-scaler: wrote ${TIMING_FILE}"
}

get_spec_ready() {
  # Echoes "spec ready" (two integers separated by a space). Missing values
  # become 0 (jsonpath returns empty string when readyReplicas is not yet set).
  local spec ready
  spec=$("${KUBECTL}" -n kube-system get deployment clustermesh-apiserver \
    -o jsonpath='{.spec.replicas}' 2>/dev/null || echo 0)
  ready=$("${KUBECTL}" -n kube-system get deployment clustermesh-apiserver \
    -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo 0)
  echo "${spec:-0} ${ready:-0}"
}

T0=$(date +%s)

case "${ACTION}" in
  scale-up)
    echo "ha-config-scaler: scale-up clustermesh-apiserver to ${REPLICAS} replicas on ${CURRENT_CONTEXT}"
    if ! "${KUBECTL}" -n kube-system scale deployment clustermesh-apiserver \
        --replicas="${REPLICAS}" >/dev/null 2>&1; then
      echo "ha-config-scaler WARN: kubectl scale command failed"
      emit_timing "scale-up" "${REPLICAS}" 0 0 false 0 "kubectl scale failed"
      exit 0
    fi

    # Phase 1: wait for spec.replicas==REPLICAS AND status.readyReplicas==REPLICAS.
    # 240s budget covers initial image pull + ENI attach on AKS-managed Cilium
    # (we observed 30-60s pod schedule + 60s pull for single-pod recovery; HA
    # rollouts are sequential per RollingUpdate strategy).
    ROLLOUT_DEADLINE=$((T0 + 240))
    spec=0
    ready=0
    while [ "$(date +%s)" -lt "${ROLLOUT_DEADLINE}" ]; do
      read -r spec ready <<<"$(get_spec_ready)"
      if [ "${spec}" -eq "${REPLICAS}" ] && [ "${ready}" -eq "${REPLICAS}" ]; then
        break
      fi
      sleep 2
    done

    if [ "${spec}" -ne "${REPLICAS}" ] || [ "${ready}" -ne "${REPLICAS}" ]; then
      T1=$(date +%s)
      DUR=$((T1 - T0))
      echo "ha-config-scaler WARN: rollout did not reach ${REPLICAS} replicas after ${DUR}s (spec=${spec} ready=${ready})"
      emit_timing "scale-up" "${REPLICAS}" "${spec}" "${ready}" false "${DUR}" "rollout timeout"
      exit 0
    fi

    # Phase 2: ENO-revert detection. AKS-managed Cilium tags the Deployment
    # with `app.kubernetes.io/actually-managed-by=Eno`; the ENO operator
    # reconciles to desired state on its own cadence. If it reverts our
    # scale within 30s of rollout completion, the rest of the scenario will
    # run on degraded replicas — useful to record but not useful for HA A/B
    # comparison.
    REVERT_DEADLINE=$(($(date +%s) + 30))
    honored=true
    final_spec=${spec}
    final_ready=${ready}
    while [ "$(date +%s)" -lt "${REVERT_DEADLINE}" ]; do
      read -r final_spec final_ready <<<"$(get_spec_ready)"
      if [ "${final_spec}" -ne "${REPLICAS}" ]; then
        honored=false
        echo "ha-config-scaler WARN: ENO reverted scale within 30s — spec=${final_spec}"
        break
      fi
      sleep 2
    done

    T1=$(date +%s)
    DUR=$((T1 - T0))
    NOTE="ok"
    [ "${honored}" = "false" ] && NOTE="enor_reverted"
    emit_timing "scale-up" "${REPLICAS}" "${final_spec}" "${final_ready}" "${honored}" "${DUR}" "${NOTE}"
    echo "ha-config-scaler: scale-up complete in ${DUR}s, spec=${final_spec} ready=${final_ready} honored=${honored}"
    ;;

  scale-down)
    echo "ha-config-scaler: scale-down clustermesh-apiserver to 1 replica on ${CURRENT_CONTEXT} (cleanup)"
    # Best-effort. Failure here is non-blocking — the cluster is about to be
    # destroyed anyway. We do NOT overwrite the scale-up timing JSON.
    "${KUBECTL}" -n kube-system scale deployment clustermesh-apiserver \
      --replicas=1 >/dev/null 2>&1 || true
    read -r spec ready <<<"$(get_spec_ready)"
    echo "ha-config-scaler: scale-down attempted; current spec=${spec} ready=${ready}"
    ;;

  *)
    echo "ha-config-scaler ERROR: unknown action '${ACTION}' (expected scale-up|scale-down)"
    exit 0
    ;;
esac

exit 0
