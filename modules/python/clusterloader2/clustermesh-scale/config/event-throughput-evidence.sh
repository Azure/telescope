#!/bin/bash
# Scenario #1 (Cross-Cluster Event Throughput) — post-execution evidence
# generator. Runs from inside the CL2 docker container via Method: Exec,
# twice per cluster:
#
#   capture — right after the warmup sleep, before the restart-burst
#             workload module call. Snapshots the steady-state pre-restart
#             world: exact Deployment/Pod counts+readiness, sorted Pod
#             UIDs, and the pre-restart pod-template generation (0).
#   verify  — immediately after the restart module's
#             WaitForControlledPodsRunning gather step. Snapshots the
#             post-restart world the same way, confirms every Deployment's
#             pod-template carries the configured restart generation, and
#             confirms zero overlap between pre- and post-restart Pod UIDs
#             (i.e. every pod was actually recreated by the rolling
#             restart, not merely marked Ready again in place).
#
# No jq/python3 in this container (same constraint as pod-churn-killer.sh /
# apiserver-failure-killer.sh) — everything below is kubectl jsonpath +
# bash/grep/sort/comm. Because merging JSON without jq is impractical, the
# capture phase persists its findings as plain KEY=VALUE + UID-list sidecar
# files next to the evidence JSON; the verify phase sources those sidecars
# and re-emits ONE fully-merged EventThroughputEvidence.json atomically
# (tmp file + mv), then removes the sidecars. Both phases always also
# (re)write the evidence JSON so a run that never reaches the verify phase
# (e.g. restart module times out) still leaves file-only proof of what the
# capture phase observed.
#
# Positional args (passed via Method: Exec command list):
#   $1 PHASE                       "capture" | "verify".
#   $2 NAMESPACES                  Namespace count (CL2_NAMESPACES).
#   $3 DEPLOYMENTS_PER_NAMESPACE   Deployments per namespace.
#   $4 REPLICAS_PER_DEPLOYMENT     Replicas per Deployment.
#   $5 WORKLOAD_GROUP              Label-selector group value.
#   $6 RESTART_GENERATION          Configured restart-generation value that
#                                  every pod-template must carry after the
#                                  restart burst (verify phase only).
#   $7 REPORT_PATH                 (optional) Evidence JSON output path.
#                                  Defaults to
#                                  /root/perf-tests/clusterloader2/results/EventThroughputEvidence.json
#   $8 POLL_TIMEOUT_SECONDS        (optional) Bounded poll budget for exact
#                                  count/readiness convergence. Default 120.
#
# Exit codes:
#   0 — this phase's contract is satisfied (capture_valid / restart_valid).
#   1 — contract failure. Evidence JSON is still written (with the actual
#       observed values) before exiting, per validator design — a failed
#       capture/verify is itself useful post-hoc signal, not a crash.
#   127 — kubectl unavailable in this CL2 image.

set -u
set -o pipefail

PHASE="${1:?phase required: capture|verify}"
NAMESPACES="${2:-5}"
DEPLOYMENTS_PER_NAMESPACE="${3:-4}"
REPLICAS_PER_DEPLOYMENT="${4:-10}"
WORKLOAD_GROUP="${5:-clustermesh-event-throughput}"
RESTART_GENERATION="${6:-1}"
REPORT_PATH="${7:-/root/perf-tests/clusterloader2/results/EventThroughputEvidence.json}"
POLL_TIMEOUT_SECONDS="${8:-120}"
POLL_INTERVAL_SECONDS=3

PRE_ENV_PATH="${REPORT_PATH}.pre.env"
PRE_UIDS_PATH="${REPORT_PATH}.pre-uids.txt"

LABEL_SELECTOR="group=${WORKLOAD_GROUP}"
EXPECTED_DEPLOYMENT_COUNT=$((NAMESPACES * DEPLOYMENTS_PER_NAMESPACE))
EXPECTED_POD_COUNT=$((EXPECTED_DEPLOYMENT_COUNT * REPLICAS_PER_DEPLOYMENT))

if command -v kubectl >/dev/null 2>&1; then
  KUBECTL=kubectl
elif [ -x /root/perf-tests/clusterloader2/config/kubectl ]; then
  KUBECTL=/root/perf-tests/clusterloader2/config/kubectl
  export PATH="$(dirname "${KUBECTL}"):${PATH}"
  echo "event-throughput-evidence: using pre-staged kubectl at ${KUBECTL}"
else
  echo "event-throughput-evidence ERROR: kubectl not in PATH and pre-staged binary missing"
  exit 127
fi

mkdir -p "$(dirname "${REPORT_PATH}")"

# json_escape STRING
#
# Minimal JSON string escaper (no jq/python3 available in this container).
# Only used for free-form text (kubectl error messages) that we embed
# verbatim into the evidence JSON — numeric/boolean fields never need it.
json_escape() {
  local s="$1"
  s="${s//\\/\\\\}"
  s="${s//\"/\\\"}"
  s="${s//$'\n'/\\n}"
  s="${s//$'\r'/}"
  s="${s//$'\t'/\\t}"
  printf '%s' "${s}"
}

# Every count_*/pod_uids_sorted query below independently captures
# kubectl's OWN exit status (not the exit status of whatever text tool
# happens to run after it). This matters because piping a failed kubectl
# straight into `wc -l` / `grep -c` (as earlier revisions of this script
# did) makes a transient API failure look EXACTLY like a legitimate "0"
# result: wc/grep read kubectl's empty stdout, print 0, and exit 0
# themselves — even `set -o pipefail` doesn't help, since pipefail only
# surfaces the last non-zero exit in the pipeline, and the downstream
# tool never fails. A failed query must never be silently coerced into
# 0 matches, 0 mismatches, or an empty (vacuously "no overlap") UID set.
#
# On success: prints the numeric result (or, for pod_uids_sorted, the
# sorted UID list) and returns 0.
# On failure: prints a one-line, human-readable error and returns 1.
# Callers MUST check the return status before trusting the printed value.

count_deployments() {
  local out rc
  out="$("${KUBECTL}" get deployments -A -l "${LABEL_SELECTOR}" --no-headers 2>&1)"
  rc=$?
  if [ "${rc}" -ne 0 ]; then
    printf 'kubectl get deployments failed (rc=%s): %s' "${rc}" "${out}"
    return 1
  fi
  if [ -z "${out}" ]; then
    printf '0'
  else
    printf '%s\n' "${out}" | wc -l | tr -d ' '
  fi
}

count_pods_total() {
  local out rc
  out="$("${KUBECTL}" get pods -A -l "${LABEL_SELECTOR}" --no-headers 2>&1)"
  rc=$?
  if [ "${rc}" -ne 0 ]; then
    printf 'kubectl get pods failed (rc=%s): %s' "${rc}" "${out}"
    return 1
  fi
  if [ -z "${out}" ]; then
    printf '0'
  else
    printf '%s\n' "${out}" | wc -l | tr -d ' '
  fi
}

count_pods_ready() {
  local out rc
  out="$("${KUBECTL}" get pods -A -l "${LABEL_SELECTOR}" \
    -o 'jsonpath={range .items[*]}{.status.conditions[?(@.type=="Ready")].status}{"\n"}{end}' 2>&1)"
  rc=$?
  if [ "${rc}" -ne 0 ]; then
    printf 'kubectl get pods (readiness) failed (rc=%s): %s' "${rc}" "${out}"
    return 1
  fi
  if [ -z "${out}" ]; then
    printf '0'
  else
    printf '%s\n' "${out}" | grep -c '^True$' || true
  fi
}

pod_uids_sorted() {
  local out rc
  out="$("${KUBECTL}" get pods -A -l "${LABEL_SELECTOR}" \
    -o 'jsonpath={range .items[*]}{.metadata.uid}{"\n"}{end}' 2>&1)"
  rc=$?
  if [ "${rc}" -ne 0 ]; then
    printf 'kubectl get pods (uids) failed (rc=%s): %s' "${rc}" "${out}"
    return 1
  fi
  if [ -n "${out}" ]; then
    printf '%s\n' "${out}" | sort
  fi
}

count_generation_mismatches() {
  # Counts Deployments whose pod-template restart-generation annotation is
  # NOT exactly the configured value. 0 == every Deployment matches.
  local out rc
  out="$("${KUBECTL}" get deployments -A -l "${LABEL_SELECTOR}" \
    -o 'jsonpath={range .items[*]}{.spec.template.metadata.annotations.restart-generation}{"\n"}{end}' 2>&1)"
  rc=$?
  if [ "${rc}" -ne 0 ]; then
    printf 'kubectl get deployments (restart-generation) failed (rc=%s): %s' "${rc}" "${out}"
    return 1
  fi
  if [ -z "${out}" ]; then
    printf '0'
  else
    printf '%s\n' "${out}" | grep -vc "^${RESTART_GENERATION}$" || true
  fi
}

# poll_exact_counts <expected_deployment_count> <expected_pod_count>
#
# Bounded poll (kubectl calls are cheap list ops, but never unbounded) that
# waits until deployment/pod/ready counts all match the exact expected
# values, or POLL_TIMEOUT_SECONDS elapses. A transient kubectl failure on
# any individual iteration is retried on the next iteration (within the
# same bound) rather than treated as fatal immediately — but each query's
# success is tracked independently and STICKILY: once a query has
# succeeded at least once it stays "ok", and its last successful value is
# retained across any later transient failures. A query that never
# succeeds even once by the deadline stays "not ok" with count 0 — that 0
# is a not-yet-observed placeholder, never a claim that kubectl actually
# reported zero, and callers must gate validity on the *_ok flags, not
# just on the numeric equality checks.
#
# Prints one line, pipe-delimited:
#   dep|pods|ready|dep_ok|pods_ok|ready_ok|dep_err|pods_err|ready_err
# Error text is newline/pipe-sanitized first (see _sanitize_for_pipe_line)
# so a kubectl error message can never desync the pipe-delimited fields.
_sanitize_for_pipe_line() {
  local s="$1"
  s="${s//$'\n'/ }"
  s="${s//|/ }"
  printf '%s' "${s}"
}

poll_exact_counts() {
  local expected_deployments="$1"
  local expected_pods="$2"
  local deadline=$(( $(date +%s) + POLL_TIMEOUT_SECONDS ))
  local dep=0 pods=0 ready=0
  local dep_ok=false pods_ok=false ready_ok=false
  local dep_err="not yet queried" pods_err="not yet queried" ready_err="not yet queried"
  local val
  while true; do
    if val=$(count_deployments); then
      dep="${val}"; dep_ok=true; dep_err=""
    else
      dep_err="${val}"
    fi
    if val=$(count_pods_total); then
      pods="${val}"; pods_ok=true; pods_err=""
    else
      pods_err="${val}"
    fi
    if val=$(count_pods_ready); then
      ready="${val}"; ready_ok=true; ready_err=""
    else
      ready_err="${val}"
    fi
    if [ "${dep_ok}" = "true" ] && [ "${pods_ok}" = "true" ] && [ "${ready_ok}" = "true" ] && \
       [ "${dep}" -eq "${expected_deployments}" ] && [ "${pods}" -eq "${expected_pods}" ] && [ "${ready}" -eq "${expected_pods}" ]; then
      break
    fi
    if [ "$(date +%s)" -ge "${deadline}" ]; then
      break
    fi
    sleep "${POLL_INTERVAL_SECONDS}"
  done
  printf '%s|%s|%s|%s|%s|%s|%s|%s|%s\n' \
    "${dep}" "${pods}" "${ready}" "${dep_ok}" "${pods_ok}" "${ready_ok}" \
    "$(_sanitize_for_pipe_line "${dep_err}")" "$(_sanitize_for_pipe_line "${pods_err}")" "$(_sanitize_for_pipe_line "${ready_err}")"
}

case "${PHASE}" in
  capture)
    echo "event-throughput-evidence: capture phase — expecting ${EXPECTED_DEPLOYMENT_COUNT} deployments / ${EXPECTED_POD_COUNT} pods (selector=${LABEL_SELECTOR})"
    IFS='|' read -r DEP_COUNT POD_COUNT READY_COUNT DEP_QUERY_OK POD_QUERY_OK READY_QUERY_OK \
      DEP_QUERY_ERR POD_QUERY_ERR READY_QUERY_ERR \
      <<<"$(poll_exact_counts "${EXPECTED_DEPLOYMENT_COUNT}" "${EXPECTED_POD_COUNT}")"

    UID_OUT="$(pod_uids_sorted)"
    UID_RC=$?
    if [ "${UID_RC}" -eq 0 ]; then
      UID_QUERY_OK=true
      UID_QUERY_ERR=""
      if [ -n "${UID_OUT}" ]; then printf '%s\n' "${UID_OUT}" > "${PRE_UIDS_PATH}"; else : > "${PRE_UIDS_PATH}"; fi
    else
      UID_QUERY_OK=false
      UID_QUERY_ERR="${UID_OUT}"
      : > "${PRE_UIDS_PATH}"
    fi

    # UID_COUNT is the raw number of Pod UID lines returned; UNIQUE_UID_COUNT
    # is the number of distinct UIDs among them (pod_uids_sorted's output is
    # already sorted, so `uniq` is sufficient to dedupe). A snapshot with
    # fewer than EXPECTED_POD_COUNT lines (partial listing) or with
    # UID_COUNT != UNIQUE_UID_COUNT (duplicate UIDs — e.g. a stale/duplicate
    # kubectl listing) must NOT be treated as a complete, trustworthy Pod
    # identity snapshot even when the raw pod/ready counts above look right.
    UID_COUNT=$(wc -l < "${PRE_UIDS_PATH}" | tr -d ' ')
    UNIQUE_UID_COUNT=$(uniq "${PRE_UIDS_PATH}" | wc -l | tr -d ' ')

    CAPTURE_VALID=false
    if [ "${DEP_QUERY_OK}" = "true" ] && [ "${POD_QUERY_OK}" = "true" ] && \
       [ "${READY_QUERY_OK}" = "true" ] && [ "${UID_QUERY_OK}" = "true" ] && \
       [ "${DEP_COUNT}" -eq "${EXPECTED_DEPLOYMENT_COUNT}" ] && \
       [ "${POD_COUNT}" -eq "${EXPECTED_POD_COUNT}" ] && \
       [ "${READY_COUNT}" -eq "${EXPECTED_POD_COUNT}" ] && \
       [ "${UID_COUNT}" -eq "${EXPECTED_POD_COUNT}" ] && \
       [ "${UNIQUE_UID_COUNT}" -eq "${EXPECTED_POD_COUNT}" ]; then
      CAPTURE_VALID=true
    fi

    # Sidecar env file: sourced verbatim by the verify phase. Integer/bool
    # fields are safe to embed directly as plain KEY=VALUE; free-form
    # kubectl error text is %q-quoted so `source`-ing it later can never
    # execute cluster-controlled content as shell code.
    cat > "${PRE_ENV_PATH}" <<EOF
PRE_EXPECTED_DEPLOYMENT_COUNT=${EXPECTED_DEPLOYMENT_COUNT}
PRE_DEPLOYMENT_COUNT=${DEP_COUNT}
PRE_EXPECTED_POD_COUNT=${EXPECTED_POD_COUNT}
PRE_POD_COUNT=${POD_COUNT}
PRE_READY_POD_COUNT=${READY_COUNT}
PRE_UID_COUNT=${UID_COUNT}
PRE_UNIQUE_UID_COUNT=${UNIQUE_UID_COUNT}
PRE_GENERATION=0
PRE_CAPTURE_VALID=${CAPTURE_VALID}
PRE_DEP_QUERY_OK=${DEP_QUERY_OK}
PRE_POD_QUERY_OK=${POD_QUERY_OK}
PRE_READY_QUERY_OK=${READY_QUERY_OK}
PRE_UID_QUERY_OK=${UID_QUERY_OK}
EOF
    printf 'PRE_DEP_QUERY_ERR=%q\n' "${DEP_QUERY_ERR}" >> "${PRE_ENV_PATH}"
    printf 'PRE_POD_QUERY_ERR=%q\n' "${POD_QUERY_ERR}" >> "${PRE_ENV_PATH}"
    printf 'PRE_READY_QUERY_ERR=%q\n' "${READY_QUERY_ERR}" >> "${PRE_ENV_PATH}"
    printf 'PRE_UID_QUERY_ERR=%q\n' "${UID_QUERY_ERR}" >> "${PRE_ENV_PATH}"

    PRE_UIDS_JSON="$(awk 'BEGIN{ORS=""} {printf "%s\"%s\"", (NR>1?",":""), $0}' "${PRE_UIDS_PATH}")"
    TMP_REPORT="${REPORT_PATH}.tmp"
    cat > "${TMP_REPORT}" <<EOF
{
  "capture_valid": ${CAPTURE_VALID},
  "restart_valid": false,
  "pre_restart": {
    "expected_deployment_count": ${EXPECTED_DEPLOYMENT_COUNT},
    "deployment_count": ${DEP_COUNT},
    "expected_pod_count": ${EXPECTED_POD_COUNT},
    "pod_count": ${POD_COUNT},
    "ready_pod_count": ${READY_COUNT},
    "pod_uids": [${PRE_UIDS_JSON}],
    "uid_count": ${UID_COUNT},
    "unique_uid_count": ${UNIQUE_UID_COUNT},
    "generation": 0,
    "query_success": {
      "deployment_count": ${DEP_QUERY_OK},
      "pod_count": ${POD_QUERY_OK},
      "ready_pod_count": ${READY_QUERY_OK},
      "pod_uids": ${UID_QUERY_OK}
    },
    "query_errors": {
      "deployment_count": "$(json_escape "${DEP_QUERY_ERR}")",
      "pod_count": "$(json_escape "${POD_QUERY_ERR}")",
      "ready_pod_count": "$(json_escape "${READY_QUERY_ERR}")",
      "pod_uids": "$(json_escape "${UID_QUERY_ERR}")"
    }
  },
  "post_restart": null
}
EOF
    mv -f "${TMP_REPORT}" "${REPORT_PATH}"

    if [ "${CAPTURE_VALID}" != "true" ]; then
      echo "event-throughput-evidence ERROR: capture phase invalid (deployments=${DEP_COUNT}/${EXPECTED_DEPLOYMENT_COUNT} pods=${POD_COUNT}/${EXPECTED_POD_COUNT} ready=${READY_COUNT}/${EXPECTED_POD_COUNT} uids=${UID_COUNT}/${EXPECTED_POD_COUNT} unique_uids=${UNIQUE_UID_COUNT}/${EXPECTED_POD_COUNT} dep_query_ok=${DEP_QUERY_OK} pod_query_ok=${POD_QUERY_OK} ready_query_ok=${READY_QUERY_OK} uid_query_ok=${UID_QUERY_OK})"
      exit 1
    fi
    echo "event-throughput-evidence: capture phase verified (deployments=${DEP_COUNT} pods=${POD_COUNT} ready=${READY_COUNT})"
    exit 0
    ;;

  verify)
    echo "event-throughput-evidence: verify phase — expecting ${EXPECTED_DEPLOYMENT_COUNT} deployments / ${EXPECTED_POD_COUNT} pods (selector=${LABEL_SELECTOR}, generation=${RESTART_GENERATION})"

    if [ ! -f "${PRE_ENV_PATH}" ] || [ ! -f "${PRE_UIDS_PATH}" ]; then
      echo "event-throughput-evidence ERROR: missing capture-phase sidecar(s) (${PRE_ENV_PATH}, ${PRE_UIDS_PATH}) — capture phase did not run or was cleaned up first"
      TMP_REPORT="${REPORT_PATH}.tmp"
      cat > "${TMP_REPORT}" <<EOF
{
  "capture_valid": false,
  "restart_valid": false,
  "pre_restart": null,
  "post_restart": null,
  "error": "missing_capture_sidecar"
}
EOF
      mv -f "${TMP_REPORT}" "${REPORT_PATH}"
      exit 1
    fi

    # shellcheck disable=SC1090
    source "${PRE_ENV_PATH}"

    IFS='|' read -r POST_DEP_COUNT POST_POD_COUNT POST_READY_COUNT POST_DEP_QUERY_OK POST_POD_QUERY_OK POST_READY_QUERY_OK \
      POST_DEP_QUERY_ERR POST_POD_QUERY_ERR POST_READY_QUERY_ERR \
      <<<"$(poll_exact_counts "${EXPECTED_DEPLOYMENT_COUNT}" "${EXPECTED_POD_COUNT}")"

    POST_UID_OUT="$(pod_uids_sorted)"
    POST_UID_RC=$?
    if [ "${POST_UID_RC}" -eq 0 ]; then
      POST_UID_QUERY_OK=true
      POST_UID_QUERY_ERR=""
      if [ -n "${POST_UID_OUT}" ]; then printf '%s\n' "${POST_UID_OUT}" > "${REPORT_PATH}.post-uids.txt"; else : > "${REPORT_PATH}.post-uids.txt"; fi
    else
      POST_UID_QUERY_OK=false
      POST_UID_QUERY_ERR="${POST_UID_OUT}"
      : > "${REPORT_PATH}.post-uids.txt"
    fi

    # Same exact-count + no-duplicates requirement as the capture phase (see
    # comment there) — POST_UID_COUNT/POST_UNIQUE_UID_COUNT must both equal
    # EXPECTED_POD_COUNT for the post-restart snapshot to be trustworthy.
    POST_UID_COUNT=$(wc -l < "${REPORT_PATH}.post-uids.txt" | tr -d ' ')
    POST_UNIQUE_UID_COUNT=$(uniq "${REPORT_PATH}.post-uids.txt" | wc -l | tr -d ' ')

    GEN_OUT="$(count_generation_mismatches)"
    GEN_RC=$?
    if [ "${GEN_RC}" -eq 0 ]; then
      GEN_QUERY_OK=true
      GEN_MISMATCHES="${GEN_OUT}"
      GEN_QUERY_ERR=""
    else
      GEN_QUERY_OK=false
      GEN_MISMATCHES=0
      GEN_QUERY_ERR="${GEN_OUT}"
    fi

    RESTART_GENERATION_VERIFIED=false
    if [ "${GEN_QUERY_OK}" = "true" ] && [ "${GEN_MISMATCHES}" -eq 0 ] && \
       [ "${POST_DEP_QUERY_OK}" = "true" ] && [ "${POST_DEP_COUNT}" -eq "${EXPECTED_DEPLOYMENT_COUNT}" ]; then
      RESTART_GENERATION_VERIFIED=true
    fi

    # A failed UID query (pre OR post) must never be allowed to masquerade
    # as "0 overlap" (vacuous truth from comm on an incomplete/empty file)
    # — RESTART_VALID below gates on PRE_UID_QUERY_OK/POST_UID_QUERY_OK
    # explicitly, regardless of what OVERLAP_COUNT computes to.
    OVERLAP_COUNT=$(comm -12 "${PRE_UIDS_PATH}" "${REPORT_PATH}.post-uids.txt" | grep -c . || true)

    RESTART_VALID=false
    if [ "${PRE_CAPTURE_VALID}" = "true" ] && \
       [ "${PRE_DEP_QUERY_OK}" = "true" ] && [ "${PRE_POD_QUERY_OK}" = "true" ] && \
       [ "${PRE_READY_QUERY_OK}" = "true" ] && [ "${PRE_UID_QUERY_OK}" = "true" ] && \
       [ "${POST_DEP_QUERY_OK}" = "true" ] && [ "${POST_POD_QUERY_OK}" = "true" ] && \
       [ "${POST_READY_QUERY_OK}" = "true" ] && [ "${POST_UID_QUERY_OK}" = "true" ] && \
       [ "${GEN_QUERY_OK}" = "true" ] && \
       [ "${POST_DEP_COUNT}" -eq "${EXPECTED_DEPLOYMENT_COUNT}" ] && \
       [ "${POST_POD_COUNT}" -eq "${EXPECTED_POD_COUNT}" ] && \
       [ "${POST_READY_COUNT}" -eq "${EXPECTED_POD_COUNT}" ] && \
       [ "${PRE_UID_COUNT}" -eq "${EXPECTED_POD_COUNT}" ] && \
       [ "${PRE_UNIQUE_UID_COUNT}" -eq "${EXPECTED_POD_COUNT}" ] && \
       [ "${POST_UID_COUNT}" -eq "${EXPECTED_POD_COUNT}" ] && \
       [ "${POST_UNIQUE_UID_COUNT}" -eq "${EXPECTED_POD_COUNT}" ] && \
       [ "${RESTART_GENERATION_VERIFIED}" = "true" ] && \
       [ "${OVERLAP_COUNT}" -eq 0 ]; then
      RESTART_VALID=true
    fi

    PRE_UIDS_JSON="$(awk 'BEGIN{ORS=""} {printf "%s\"%s\"", (NR>1?",":""), $0}' "${PRE_UIDS_PATH}")"
    POST_UIDS_JSON="$(awk 'BEGIN{ORS=""} {printf "%s\"%s\"", (NR>1?",":""), $0}' "${REPORT_PATH}.post-uids.txt")"

    TMP_REPORT="${REPORT_PATH}.tmp"
    cat > "${TMP_REPORT}" <<EOF
{
  "capture_valid": ${PRE_CAPTURE_VALID},
  "restart_valid": ${RESTART_VALID},
  "pre_restart": {
    "expected_deployment_count": ${PRE_EXPECTED_DEPLOYMENT_COUNT},
    "deployment_count": ${PRE_DEPLOYMENT_COUNT},
    "expected_pod_count": ${PRE_EXPECTED_POD_COUNT},
    "pod_count": ${PRE_POD_COUNT},
    "ready_pod_count": ${PRE_READY_POD_COUNT},
    "pod_uids": [${PRE_UIDS_JSON}],
    "uid_count": ${PRE_UID_COUNT},
    "unique_uid_count": ${PRE_UNIQUE_UID_COUNT},
    "generation": ${PRE_GENERATION},
    "query_success": {
      "deployment_count": ${PRE_DEP_QUERY_OK},
      "pod_count": ${PRE_POD_QUERY_OK},
      "ready_pod_count": ${PRE_READY_QUERY_OK},
      "pod_uids": ${PRE_UID_QUERY_OK}
    },
    "query_errors": {
      "deployment_count": "$(json_escape "${PRE_DEP_QUERY_ERR}")",
      "pod_count": "$(json_escape "${PRE_POD_QUERY_ERR}")",
      "ready_pod_count": "$(json_escape "${PRE_READY_QUERY_ERR}")",
      "pod_uids": "$(json_escape "${PRE_UID_QUERY_ERR}")"
    }
  },
  "post_restart": {
    "expected_deployment_count": ${EXPECTED_DEPLOYMENT_COUNT},
    "deployment_count": ${POST_DEP_COUNT},
    "expected_pod_count": ${EXPECTED_POD_COUNT},
    "pod_count": ${POST_POD_COUNT},
    "ready_pod_count": ${POST_READY_COUNT},
    "pod_uids": [${POST_UIDS_JSON}],
    "uid_count": ${POST_UID_COUNT},
    "unique_uid_count": ${POST_UNIQUE_UID_COUNT},
    "configured_restart_generation": ${RESTART_GENERATION},
    "restart_generation_verified": ${RESTART_GENERATION_VERIFIED},
    "pre_post_uid_overlap_count": ${OVERLAP_COUNT},
    "query_success": {
      "deployment_count": ${POST_DEP_QUERY_OK},
      "pod_count": ${POST_POD_QUERY_OK},
      "ready_pod_count": ${POST_READY_QUERY_OK},
      "pod_uids": ${POST_UID_QUERY_OK},
      "generation": ${GEN_QUERY_OK}
    },
    "query_errors": {
      "deployment_count": "$(json_escape "${POST_DEP_QUERY_ERR}")",
      "pod_count": "$(json_escape "${POST_POD_QUERY_ERR}")",
      "ready_pod_count": "$(json_escape "${POST_READY_QUERY_ERR}")",
      "pod_uids": "$(json_escape "${POST_UID_QUERY_ERR}")",
      "generation": "$(json_escape "${GEN_QUERY_ERR}")"
    }
  }
}
EOF
    mv -f "${TMP_REPORT}" "${REPORT_PATH}"
    rm -f "${PRE_ENV_PATH}" "${PRE_UIDS_PATH}" "${REPORT_PATH}.post-uids.txt"

    if [ "${RESTART_VALID}" != "true" ]; then
      echo "event-throughput-evidence ERROR: verify phase invalid (deployments=${POST_DEP_COUNT}/${EXPECTED_DEPLOYMENT_COUNT} pods=${POST_POD_COUNT}/${EXPECTED_POD_COUNT} ready=${POST_READY_COUNT}/${EXPECTED_POD_COUNT} pre_uids=${PRE_UID_COUNT}/${EXPECTED_POD_COUNT} pre_unique_uids=${PRE_UNIQUE_UID_COUNT}/${EXPECTED_POD_COUNT} post_uids=${POST_UID_COUNT}/${EXPECTED_POD_COUNT} post_unique_uids=${POST_UNIQUE_UID_COUNT}/${EXPECTED_POD_COUNT} gen_verified=${RESTART_GENERATION_VERIFIED} overlap=${OVERLAP_COUNT} dep_query_ok=${POST_DEP_QUERY_OK} pod_query_ok=${POST_POD_QUERY_OK} ready_query_ok=${POST_READY_QUERY_OK} uid_query_ok=${POST_UID_QUERY_OK} generation_query_ok=${GEN_QUERY_OK})"
      exit 1
    fi
    echo "event-throughput-evidence: verify phase confirmed (deployments=${POST_DEP_COUNT} pods=${POST_POD_COUNT} ready=${POST_READY_COUNT} overlap=${OVERLAP_COUNT})"
    exit 0
    ;;

  *)
    echo "event-throughput-evidence ERROR: unknown phase '${PHASE}' (expected capture|verify)"
    exit 1
    ;;
esac
