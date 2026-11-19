#!/usr/bin/env bash
set -euo pipefail

[[ "$CLOUD" == aks && "$CL2_IMAGE" == ghcr.io/azure/clusterloader2:v20250513 ]]
[[ "${SCRAPE_KUBELETS,,}" == true && "${SCRAPE_CONTAINERD:-False}" =~ ^[Ff]alse$ ]]
mkdir -p "$CL2_REPORT_DIR"
[[ -z "$(ls -A "$CL2_REPORT_DIR")" ]]
k=(kubectl --kubeconfig "$HOME/.kube/config" --request-timeout=30s -n cl2-cri-pilot)
root=/root/perf-tests/clusterloader2
pod=

finish() {
  rc=$?
  if [[ -n "$pod" ]]; then
    "${k[@]}" logs "$pod" > "$CL2_REPORT_DIR/cl2-driver.log" 2>&1 || true
  fi
  "${k[@]}" delete namespace,clusterrole,clusterrolebinding cl2-cri-pilot \
    --ignore-not-found --wait=false || echo "CL2 pilot cleanup failed; Terraform teardown must remove the cluster" >&2
  exit "$rc"
}

echo "CL2 pilot grants cluster-wide RBAC only on this disposable test cluster."
"${k[@]}" create namespace cl2-cri-pilot
trap finish EXIT
"${k[@]}" create configmap cl2-cri-pilot --from-file="$CL2_CONFIG_DIR"
"${k[@]}" create -f "$(dirname "$0")/pilot-job.yml"
deadline=$((SECONDS + 3600))
while (( SECONDS < deadline )); do
  pod=$("${k[@]}" get pods -l job-name=cl2-cri-pilot -o 'jsonpath={.items[*].metadata.name}')
  failed=$("${k[@]}" get job cl2-cri-pilot -o 'jsonpath={.status.conditions[?(@.type=="Failed")].status}')
  [[ "$failed" != True ]] || { echo "CL2 Job failed before report collection" >&2; exit 1; }
  if [[ -n "$pod" ]]; then
    phase=$("${k[@]}" get pod "$pod" -o 'jsonpath={.status.phase}')
    [[ "$phase" != Failed && "$phase" != Succeeded ]] || {
      echo "CL2 Pod terminated before report collection" >&2; exit 1;
    }
    if [[ "$phase" == Running ]] && code=$("${k[@]}" exec "$pod" -- cat "$root/exit-code" 2>/dev/null); then
      [[ "$code" =~ ^[0-9]+$ && "$code" -le 255 ]]
      "${k[@]}" cp "$pod:$root/results/." "$CL2_REPORT_DIR"
      "${k[@]}" exec "$pod" -- touch "$root/reports-collected"
      "${k[@]}" wait --for=jsonpath='{.status.containerStatuses[0].state.terminated.exitCode}'="$code" \
        "pod/$pod" --timeout=60s
      if [[ "$code" == 0 ]]; then
        test -s "$CL2_REPORT_DIR/junit.xml"
      fi
      exit "$code"
    fi
  fi
  sleep 5
done
echo "CL2 pilot timed out" >&2
exit 124
