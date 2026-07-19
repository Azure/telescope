#!/usr/bin/env bash
set -euo pipefail

enabled="${CL2_ACNS_TELEMETRY_ENABLED:-false}"
if [ "${enabled,,}" != "true" ]; then
  exit 0
fi

: "${KUBECONFIG:?KUBECONFIG is required}"
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
timeout_seconds="${CL2_ACNS_SETUP_TIMEOUT_SECONDS:-600}"
deadline=$(( $(date +%s) + timeout_seconds ))

for crd in \
  containernetworklogs.acn.azure.com \
  ciliumnetworkpolicies.cilium.io; do
  until kubectl get "crd/$crd" >/dev/null 2>&1; do
    if [ "$(date +%s)" -ge "$deadline" ]; then
      echo "Timed out waiting for ACNS CRD $crd" >&2
      exit 1
    fi
    sleep 10
  done
done

kubectl apply \
  -f "$script_dir/acns/probe.yaml" \
  -f "$script_dir/acns/container-network-log.yaml" \
  -f "$script_dir/acns/log-collector.yaml" >/dev/null

kubectl -n acns-telemetry rollout status deployment/acns-server \
  --timeout="${timeout_seconds}s" >/dev/null
kubectl -n acns-telemetry rollout status deployment/acns-client \
  --timeout="${timeout_seconds}s" >/dev/null
kubectl -n acns-telemetry rollout status daemonset/acns-log-collector \
  --timeout="${timeout_seconds}s" >/dev/null

deadline=$(( $(date +%s) + timeout_seconds ))
while [ "$(date +%s)" -lt "$deadline" ]; do
  state=$(kubectl get containernetworklog clustermesh-scale-acns \
    -o jsonpath='{.status.state}' 2>/dev/null || true)
  if [ "$state" = "CONFIGURED" ]; then
    echo "ACNS telemetry probe and filtered container network logs are configured."
    exit 0
  fi
  if [ "$state" = "FAILED" ]; then
    kubectl describe containernetworklog clustermesh-scale-acns >&2 || true
    exit 1
  fi
  sleep 10
done

echo "Timed out waiting for ContainerNetworkLog configuration." >&2
exit 1
