#!/bin/bash
# Annotate workload namespaces for ACNS (managed Cilium) opt-in cross-cluster sync.
#
# AKS-managed Cilium ships with `clustermesh-default-global-namespace=false`
# (opt-in mode, per ACNS team confirmation 2026-05-11 from David Vadas /
# Isaiah Raya), unlike upstream Cilium which defaults to opt-out. Without
# the `clustermesh.cilium.io/global: "true"` annotation on the workload
# namespace, NONE of the namespace's resources (CiliumIdentity,
# CiliumEndpoint, CiliumEndpointSlice, Services, ServiceExports) sync
# across the mesh — even if the Service object itself carries
# `service.cilium.io/global: "true"`. The namespace annotation is
# load-bearing; once present, Cilium auto-applies the service-level
# semantics to all services in that namespace.
#
# This script is invoked via `Method: Exec` from each scale-test scenario's
# top-level CL2 config (event-throughput.yaml, pod-churn-*.yaml). It runs
# AFTER CL2 has created the test namespaces (`<prefix>-1..N`) and BEFORE the
# workload deploy phase, so cross-cluster sync is enabled from the first
# resource creation.
#
# The pre-staged kubectl binary at /root/perf-tests/clusterloader2/config/kubectl
# (set up by steps/engine/clusterloader2/clustermesh-scale/execute.yml) is
# used because the CL2 image does not bundle kubectl.
#
# Positional args:
#   $1 NAMESPACE_COUNT   How many namespaces (matches CL2's `namespace.number`).
#   $2 NAMESPACE_PREFIX  Namespace prefix (matches CL2's `namespace.prefix`).

set -u
set -o pipefail

NAMESPACE_COUNT="${1:-0}"
NAMESPACE_PREFIX="${2:-}"

if [ -z "${NAMESPACE_PREFIX}" ] || [ "${NAMESPACE_COUNT}" -lt 1 ]; then
  echo "annotate-namespaces ERROR: need positional args (count, prefix); got count='${NAMESPACE_COUNT}' prefix='${NAMESPACE_PREFIX}'"
  exit 2
fi

# Prefer PATH kubectl, fall back to the pre-staged binary the pipeline
# downloads into the bind-mounted config dir. Mirrors pod-churn-killer.sh's
# fallback path so both scripts behave consistently if the CL2 image
# eventually starts bundling kubectl.
if command -v kubectl >/dev/null 2>&1; then
  KUBECTL=kubectl
elif [ -x /root/perf-tests/clusterloader2/config/kubectl ]; then
  KUBECTL=/root/perf-tests/clusterloader2/config/kubectl
  echo "annotate-namespaces: using pre-staged kubectl at ${KUBECTL}"
else
  echo "annotate-namespaces ERROR: kubectl not in PATH and pre-staged binary missing"
  exit 127
fi

ANNOTATION="clustermesh.cilium.io/global=true"
echo "annotate-namespaces: applying ${ANNOTATION} to ${NAMESPACE_COUNT} namespaces with prefix '${NAMESPACE_PREFIX}'"

FAIL_COUNT=0
for i in $(seq 1 "${NAMESPACE_COUNT}"); do
  NS="${NAMESPACE_PREFIX}-${i}"
  # --overwrite tolerates re-runs (CL2 retries, multi-step configs). The
  # namespace MUST already exist — CL2 creates managed namespaces before
  # the first test step runs. If it's missing here, that's a real bug
  # worth surfacing as an error (don't --ignore-not-found).
  if "${KUBECTL}" annotate namespace "${NS}" "${ANNOTATION}" --overwrite >/dev/null 2>&1; then
    echo "annotate-namespaces: ${NS} annotated"
  else
    echo "annotate-namespaces ERROR: failed to annotate ${NS}"
    FAIL_COUNT=$((FAIL_COUNT + 1))
  fi
done

if [ "${FAIL_COUNT}" -gt 0 ]; then
  echo "annotate-namespaces: ${FAIL_COUNT}/${NAMESPACE_COUNT} namespaces failed annotation"
  exit 1
fi

echo "annotate-namespaces: done, ${NAMESPACE_COUNT} namespaces annotated"
exit 0
