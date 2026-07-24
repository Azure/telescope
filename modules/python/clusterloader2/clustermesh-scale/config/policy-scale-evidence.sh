#!/bin/bash
# Scenario: NetworkPolicy at scale (policy-scale.yaml) — post-execution
# evidence generator. Runs from inside the CL2 docker container via
# Method: Exec, twice per cluster:
#
#   active  — right after Phase 2 (CNP creation), before the steady-state
#             hold sleep. Bounded-polls the CiliumNetworkPolicies labeled
#             group=clustermesh-policy-scale across the
#             clustermesh-pscale-* namespaces until the exact expected
#             total AND exact per-namespace count are observed (or the
#             poll budget expires).
#   deleted — immediately after Phase 4 (CNP deletion sweep), before the
#             backend workload teardown. Bounded-polls until zero matching
#             CNPs remain anywhere in those namespaces.
#
# No jq/python3 in this container (same constraint as pod-churn-killer.sh /
# event-throughput-evidence.sh) — everything below is kubectl + bash/grep/
# sort/wc. The active phase persists its findings as a sidecar JSON
# fragment (the rendered "active" object body) next to the evidence file;
# the deleted phase inlines that fragment verbatim to atomically produce
# ONE fully-merged PolicyScaleEvidence.json (tmp file + mv), then removes
# the sidecar. Both phases always (re)write the evidence JSON — with
# verified=false and actionable detail on failure — before a nonzero exit,
# so a run that never reaches the deleted phase still leaves file-only
# proof of what the active phase observed.
#
# Namespaces are discovered dynamically (kubectl get ns matched against
# the configured prefix) rather than assumed to be "<prefix>-<n>" for
# n=1..N, so this stays correct even if CL2's namespace-naming scheme
# changes upstream.
#
# Positional args (passed via Method: Exec command list):
#   $1 PHASE                    "active" | "deleted".
#   $2 NAMESPACES               Namespace count (CL2_NAMESPACES).
#   $3 CNP_PER_NAMESPACE        Expected CiliumNetworkPolicy count per
#                               namespace (CL2_POLICY_SCALE_CNP_PER_NS).
#   $4 REPORT_PATH              (optional) Evidence JSON output path.
#                               Defaults to
#                               /root/perf-tests/clusterloader2/results/PolicyScaleEvidence.json
#   $5 POLL_TIMEOUT_SECONDS      (optional) Bounded poll budget. Default
#                               900 (15m) — sized for n=100 CNPs/ns per the
#                               scenario's own default sweep.
#   $6 NAMESPACE_PREFIX          (optional) Namespace prefix. Default
#                               "clustermesh-pscale" (matches
#                               policy-scale.yaml's `namespace.prefix`).
#   $7 WORKLOAD_GROUP            (optional) CNP label-selector group value.
#                               Default "clustermesh-policy-scale".
#
# Exit codes:
#   0 — this phase's contract is satisfied (active.verified / deleted.verified).
#   1 — contract failure. Evidence JSON is still written (with the actual
#       observed values) before exiting.
#   127 — kubectl unavailable in this CL2 image.

set -u
set -o pipefail

PHASE="${1:?phase required: active|deleted}"
NAMESPACES="${2:-5}"
CNP_PER_NAMESPACE="${3:-50}"
REPORT_PATH="${4:-/root/perf-tests/clusterloader2/results/PolicyScaleEvidence.json}"
POLL_TIMEOUT_SECONDS="${5:-900}"
NAMESPACE_PREFIX="${6:-clustermesh-pscale}"
WORKLOAD_GROUP="${7:-clustermesh-policy-scale}"
POLL_INTERVAL_SECONDS=5

ACTIVE_SIDECAR="${REPORT_PATH}.active-section.json"
LABEL_SELECTOR="group=${WORKLOAD_GROUP}"
EXPECTED_TOTAL=$((NAMESPACES * CNP_PER_NAMESPACE))

if command -v kubectl >/dev/null 2>&1; then
  KUBECTL=kubectl
elif [ -x /root/perf-tests/clusterloader2/config/kubectl ]; then
  KUBECTL=/root/perf-tests/clusterloader2/config/kubectl
  export PATH="$(dirname "${KUBECTL}"):${PATH}"
  echo "policy-scale-evidence: using pre-staged kubectl at ${KUBECTL}"
else
  echo "policy-scale-evidence ERROR: kubectl not in PATH and pre-staged binary missing"
  exit 127
fi

mkdir -p "$(dirname "${REPORT_PATH}")"

# json_escape STRING
#
# Minimal JSON string escaper (no jq/python3 available in this container).
# Only used for free-form text (kubectl error messages) embedded verbatim
# into the evidence JSON — numeric/boolean fields never need it.
json_escape() {
  local s="$1"
  s="${s//\\/\\\\}"
  s="${s//\"/\\\"}"
  s="${s//$'\n'/\\n}"
  s="${s//$'\r'/}"
  s="${s//$'\t'/\\t}"
  printf '%s' "${s}"
}

# _sanitize_for_pipe_line STRING
#
# Strips newlines/pipes from free-form error text before it's packed into
# a "|"-delimited line, so a kubectl error message can never desync a
# pipe-delimited field split.
_sanitize_for_pipe_line() {
  local s="$1"
  s="${s//$'\n'/ }"
  s="${s//|/ }"
  printf '%s' "${s}"
}

# discover_namespaces / count_cnp_in_namespace each independently capture
# kubectl's OWN exit status (not the exit status of whatever text tool
# runs after it in the pipeline). Piping a failed kubectl straight into
# `wc -l` / `grep` (as earlier revisions of this script did) makes a
# transient API failure look EXACTLY like a legitimate "0 CNPs" or "0
# namespaces" result — even `set -o pipefail` doesn't help, since it only
# surfaces the LAST non-zero exit in the pipeline, and the downstream text
# tool never fails on empty input. A failed query must never be coerced
# into 0 CNPs — that's especially dangerous for the deleted phase, where
# "0 CNPs" IS the success condition, so a masked failure there would look
# identical to confirmed deletion.
#
# On success: prints the result (namespace list / numeric count) and
# returns 0. On failure: prints a one-line, human-readable error and
# returns 1. Callers MUST check the return status before trusting the
# printed value.

discover_namespaces() {
  local out rc
  out="$("${KUBECTL}" get ns -o name 2>&1)"
  rc=$?
  if [ "${rc}" -ne 0 ]; then
    printf 'kubectl get ns failed (rc=%s): %s' "${rc}" "${out}"
    return 1
  fi
  printf '%s\n' "${out}" | sed 's#^namespace/##' | grep -E "^${NAMESPACE_PREFIX}-[0-9]+$" | sort -V
  return 0
}

count_cnp_in_namespace() {
  local out rc
  out="$("${KUBECTL}" get ciliumnetworkpolicies -n "$1" -l "${LABEL_SELECTOR}" --no-headers 2>&1)"
  rc=$?
  if [ "${rc}" -ne 0 ]; then
    printf 'kubectl get cnp -n %s failed (rc=%s): %s' "$1" "${rc}" "${out}"
    return 1
  fi
  if [ -z "${out}" ]; then
    printf '0'
  else
    printf '%s\n' "${out}" | wc -l | tr -d ' '
  fi
}

# count_cnp_total_across_prefix
#
# Used by the deleted phase, which only needs a total (no per-namespace
# breakdown) — sums per matching namespace so stray CNPs in unrelated
# namespaces never mask a real deletion failure. Namespace discovery and
# EVERY per-namespace count are tracked for success; if any of them
# failed, the returned total is NOT a trustworthy "0" even when it
# numerically comes out to 0.
#
# Prints one line, pipe-delimited: total|query_ok|query_error
count_cnp_total_across_prefix() {
  local total=0 ok=true err="" ns c ns_list
  if ns_list="$(discover_namespaces)"; then
    :
  else
    err="${ns_list}"
    ns_list=""
    ok=false
  fi
  while IFS= read -r ns; do
    [ -z "${ns}" ] && continue
    if c="$(count_cnp_in_namespace "${ns}")"; then
      :
    else
      ok=false
      if [ -n "${err}" ]; then err="${err}; "; fi
      err="${err}${c}"
      c=0
    fi
    total=$((total + c))
  done <<< "${ns_list}"
  printf '%s|%s|%s\n' "${total}" "${ok}" "$(_sanitize_for_pipe_line "${err}")"
}

case "${PHASE}" in
  active)
    echo "policy-scale-evidence: active phase — expecting ${EXPECTED_TOTAL} CNPs total (${CNP_PER_NAMESPACE}/ns across ${NAMESPACES} '${NAMESPACE_PREFIX}-*' namespaces, selector=${LABEL_SELECTOR})"
    START_EPOCH=$(date +%s)
    DEADLINE=$((START_EPOCH + POLL_TIMEOUT_SECONDS))
    NAMESPACE_LIST=""
    TOTAL=0
    ALL_EXACT=false
    NAMESPACE_COUNT=0
    ALL_QUERIES_OK=false
    QUERY_ERRORS_JSON=""

    while true; do
      ALL_QUERIES_OK=true
      QUERY_ERRORS_JSON=""
      if NAMESPACE_LIST="$(discover_namespaces)"; then
        DISCOVERY_ERR=""
      else
        ALL_QUERIES_OK=false
        DISCOVERY_ERR="${NAMESPACE_LIST}"
        NAMESPACE_LIST=""
      fi
      QUERY_ERRORS_JSON="\"namespace_discovery\": \"$(json_escape "${DISCOVERY_ERR}")\""
      NAMESPACE_COUNT=$(printf '%s\n' "${NAMESPACE_LIST}" | grep -c . || true)
      TOTAL=0
      ALL_EXACT=true
      NS_COUNTS_JSON=""
      NS_ERRORS_JSON=""
      while IFS= read -r ns; do
        [ -z "${ns}" ] && continue
        if c="$(count_cnp_in_namespace "${ns}")"; then
          ns_err=""
        else
          ALL_QUERIES_OK=false
          ns_err="${c}"
          c=0
        fi
        TOTAL=$((TOTAL + c))
        if [ "${c}" -ne "${CNP_PER_NAMESPACE}" ] || [ -n "${ns_err}" ]; then
          ALL_EXACT=false
        fi
        if [ -n "${NS_COUNTS_JSON}" ]; then
          NS_COUNTS_JSON="${NS_COUNTS_JSON},"
          NS_ERRORS_JSON="${NS_ERRORS_JSON},"
        fi
        NS_COUNTS_JSON="${NS_COUNTS_JSON}\"${ns}\": ${c}"
        NS_ERRORS_JSON="${NS_ERRORS_JSON}\"${ns}\": \"$(json_escape "${ns_err}")\""
      done <<< "${NAMESPACE_LIST}"
      QUERY_ERRORS_JSON="${QUERY_ERRORS_JSON}, \"namespace_counts\": {${NS_ERRORS_JSON}}"

      if [ "${ALL_QUERIES_OK}" = "true" ] && [ "${TOTAL}" -eq "${EXPECTED_TOTAL}" ] && \
         [ "${NAMESPACE_COUNT}" -eq "${NAMESPACES}" ] && [ "${ALL_EXACT}" = "true" ]; then
        break
      fi
      if [ "$(date +%s)" -ge "${DEADLINE}" ]; then
        break
      fi
      sleep "${POLL_INTERVAL_SECONDS}"
    done

    ELAPSED=$(( $(date +%s) - START_EPOCH ))
    ACTIVE_VERIFIED=false
    if [ "${ALL_QUERIES_OK}" = "true" ] && [ "${TOTAL}" -eq "${EXPECTED_TOTAL}" ] && \
       [ "${NAMESPACE_COUNT}" -eq "${NAMESPACES}" ] && [ "${ALL_EXACT}" = "true" ]; then
      ACTIVE_VERIFIED=true
    fi

    ACTIVE_SECTION=$(cat <<EOF
{
    "expected_total": ${EXPECTED_TOTAL},
    "observed_total": ${TOTAL},
    "expected_namespace_count": ${NAMESPACES},
    "observed_namespace_count": ${NAMESPACE_COUNT},
    "expected_per_namespace": ${CNP_PER_NAMESPACE},
    "namespace_counts": {${NS_COUNTS_JSON}},
    "verified": ${ACTIVE_VERIFIED},
    "elapsed_seconds": ${ELAPSED},
    "timeout_seconds": ${POLL_TIMEOUT_SECONDS},
    "query_success": ${ALL_QUERIES_OK},
    "query_errors": {${QUERY_ERRORS_JSON}}
  }
EOF
)
    printf '%s' "${ACTIVE_SECTION}" > "${ACTIVE_SIDECAR}"

    TMP_REPORT="${REPORT_PATH}.tmp"
    cat > "${TMP_REPORT}" <<EOF
{
  "active": ${ACTIVE_SECTION},
  "deleted": null
}
EOF
    mv -f "${TMP_REPORT}" "${REPORT_PATH}"

    if [ "${ACTIVE_VERIFIED}" != "true" ]; then
      echo "policy-scale-evidence ERROR: active phase invalid (total=${TOTAL}/${EXPECTED_TOTAL} namespaces=${NAMESPACE_COUNT}/${NAMESPACES} all_exact=${ALL_EXACT} query_success=${ALL_QUERIES_OK}) after ${ELAPSED}s"
      exit 1
    fi
    echo "policy-scale-evidence: active phase verified (total=${TOTAL} across ${NAMESPACE_COUNT} namespaces, ${ELAPSED}s)"
    exit 0
    ;;

  deleted)
    echo "policy-scale-evidence: deleted phase — waiting for 0 CNPs across '${NAMESPACE_PREFIX}-*' namespaces (selector=${LABEL_SELECTOR})"

    if [ ! -f "${ACTIVE_SIDECAR}" ]; then
      echo "policy-scale-evidence ERROR: missing active-phase sidecar (${ACTIVE_SIDECAR}) — active phase did not run or was cleaned up first"
      TMP_REPORT="${REPORT_PATH}.tmp"
      cat > "${TMP_REPORT}" <<EOF
{
  "active": null,
  "deleted": null,
  "error": "missing_active_sidecar"
}
EOF
      mv -f "${TMP_REPORT}" "${REPORT_PATH}"
      exit 1
    fi
    ACTIVE_SECTION="$(cat "${ACTIVE_SIDECAR}")"

    START_EPOCH=$(date +%s)
    DEADLINE=$((START_EPOCH + POLL_TIMEOUT_SECONDS))
    OBSERVED_COUNT=0
    QUERY_OK=false
    QUERY_ERR="not yet queried"
    REPAIR_DELETE_REQUESTED=false
    REPAIR_DELETE_ERRORS=""

    # The CL2 deletion phase is primary. If it left matching CNPs behind,
    # re-issue an idempotent label-scoped delete before polling so evidence
    # collection also repairs the exact scenario-owned residue it validates.
    IFS='|' read -r OBSERVED_COUNT QUERY_OK QUERY_ERR <<<"$(count_cnp_total_across_prefix)"
    if [ "${QUERY_OK}" = "true" ] && [ "${OBSERVED_COUNT}" -gt 0 ]; then
      REPAIR_DELETE_REQUESTED=true
      echo "policy-scale-evidence: ${OBSERVED_COUNT} CNP(s) remain after the CL2 delete phase; issuing bounded label-scoped cleanup"
      if REPAIR_NAMESPACES="$(discover_namespaces)"; then
        while IFS= read -r ns; do
          [ -z "${ns}" ] && continue
          DELETE_OUT="$("${KUBECTL}" delete ciliumnetworkpolicies -n "${ns}" \
            -l "${LABEL_SELECTOR}" --ignore-not-found=true --wait=false 2>&1)"
          DELETE_RC=$?
          if [ "${DELETE_RC}" -ne 0 ]; then
            if [ -n "${REPAIR_DELETE_ERRORS}" ]; then
              REPAIR_DELETE_ERRORS="${REPAIR_DELETE_ERRORS}; "
            fi
            REPAIR_DELETE_ERRORS="${REPAIR_DELETE_ERRORS}kubectl delete cnp -n ${ns} failed (rc=${DELETE_RC}): ${DELETE_OUT}"
          fi
        done <<< "${REPAIR_NAMESPACES}"
      else
        REPAIR_DELETE_ERRORS="${REPAIR_NAMESPACES}"
      fi
    fi

    while true; do
      IFS='|' read -r OBSERVED_COUNT QUERY_OK QUERY_ERR <<<"$(count_cnp_total_across_prefix)"
      if [ "${QUERY_OK}" = "true" ] && [ "${OBSERVED_COUNT}" -eq 0 ]; then
        break
      fi
      if [ "$(date +%s)" -ge "${DEADLINE}" ]; then
        break
      fi
      sleep "${POLL_INTERVAL_SECONDS}"
    done
    ELAPSED=$(( $(date +%s) - START_EPOCH ))

    # A persistent kubectl failure must NEVER be accepted as "0 CNPs
    # remaining" — DELETED_VERIFIED requires an actually-successful query
    # that observed zero, not merely a numeric 0 (which a failed/suppressed
    # query would also produce).
    DELETED_VERIFIED=false
    if [ "${QUERY_OK}" = "true" ] && [ "${OBSERVED_COUNT}" -eq 0 ]; then
      DELETED_VERIFIED=true
    fi

    TMP_REPORT="${REPORT_PATH}.tmp"
    cat > "${TMP_REPORT}" <<EOF
{
  "active": ${ACTIVE_SECTION},
  "deleted": {
    "observed_count": ${OBSERVED_COUNT},
    "verified": ${DELETED_VERIFIED},
    "elapsed_seconds": ${ELAPSED},
    "timeout_seconds": ${POLL_TIMEOUT_SECONDS},
    "query_success": ${QUERY_OK},
    "query_error": "$(json_escape "${QUERY_ERR}")",
    "repair_delete_requested": ${REPAIR_DELETE_REQUESTED},
    "repair_delete_errors": "$(json_escape "${REPAIR_DELETE_ERRORS}")"
  }
}
EOF
    mv -f "${TMP_REPORT}" "${REPORT_PATH}"
    rm -f "${ACTIVE_SIDECAR}"

    if [ "${DELETED_VERIFIED}" != "true" ]; then
      echo "policy-scale-evidence ERROR: deleted phase invalid (observed_count=${OBSERVED_COUNT}, expected 0, query_success=${QUERY_OK}) after ${ELAPSED}s"
      exit 1
    fi
    echo "policy-scale-evidence: deleted phase verified (0 CNPs remaining, ${ELAPSED}s)"
    exit 0
    ;;

  *)
    echo "policy-scale-evidence ERROR: unknown phase '${PHASE}' (expected active|deleted)"
    exit 1
    ;;
esac
