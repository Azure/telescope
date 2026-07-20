#!/usr/bin/env bash
set -euo pipefail

enabled="${CL2_ACNS_TELEMETRY_ENABLED:-false}"
if [ "${enabled,,}" != "true" ]; then
  exit 0
fi

: "${KUBECONFIG:?KUBECONFIG is required}"
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
timeout_seconds="${CL2_ACNS_SETUP_TIMEOUT_SECONDS:-600}"
metric_ready_timeout_seconds="${CL2_ACNS_METRIC_READY_TIMEOUT_SECONDS:-180}"
metric_poll_seconds="${CL2_ACNS_METRIC_POLL_SECONDS:-10}"
deadline=$(( $(date +%s) + timeout_seconds ))

for crd in \
  containernetworklogs.acn.azure.com \
  containernetworkmetrics.acn.azure.com \
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
  -f "$script_dir/acns/container-network-metric.yaml" \
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
  log_state=$(kubectl get containernetworklog clustermesh-scale-acns \
    -o jsonpath='{.status.state}' 2>/dev/null || true)
  metric_state=$(kubectl get containernetworkmetric container-network-metric \
    -o jsonpath='{.status.state}' 2>/dev/null || true)
  if [ "$log_state" = "CONFIGURED" ] &&
     [ "$metric_state" = "CONFIGURED" ]; then
    break
  fi
  if [ "$log_state" = "FAILED" ]; then
    kubectl describe containernetworklog clustermesh-scale-acns >&2 || true
    exit 1
  fi
  if [ "$metric_state" = "FAILED" ]; then
    kubectl describe containernetworkmetric container-network-metric >&2 || true
    exit 1
  fi
  sleep 10
done

if [ "${log_state:-}" != "CONFIGURED" ] ||
   [ "${metric_state:-}" != "CONFIGURED" ]; then
  echo "Timed out waiting for ACNS resource configuration: ContainerNetworkLog=${log_state:-missing} ContainerNetworkMetric=${metric_state:-missing}" >&2
  kubectl get containernetworklog clustermesh-scale-acns -o yaml >&2 || true
  kubectl get containernetworkmetric container-network-metric -o yaml >&2 || true
  exit 1
fi

metric_deadline=$(( $(date +%s) + metric_ready_timeout_seconds ))
last_endpoint="unavailable"
last_probe_error="no Running acns-client Pod found in acns-telemetry namespace"
last_metrics=""
# acns-client is the DNS traffic generator (see acns/probe.yaml). Only the
# Cilium/Hubble endpoint co-located on the SAME node as the Running
# acns-client Pod is guaranteed to observe its DNS traffic and expose
# hubble_dns_queries_total/hubble_dns_responses_total. An arbitrary
# "first" Cilium Pod (e.g. picked alphabetically or by list order) may sit
# on a node with no DNS activity and can false-fail readiness even though
# ACNS is correctly configured. Re-resolve client/cilium/collector on
# every poll since the client Deployment can be rescheduled to a new node.
while true; do
  client_pod=""
  client_node=""
  cilium_pod=""
  cilium_node=""
  cilium_endpoint=""
  collector_pod=""

  if IFS=$'\t' read -r client_pod client_node < <(
    kubectl -n acns-telemetry get pods -l app=acns-client \
      -o jsonpath='{range .items[?(@.status.phase=="Running")]}{.metadata.name}{"\t"}{.spec.nodeName}{"\n"}{end}' \
      2>/dev/null | head -1
  ) && [ -n "$client_pod" ] && [ -n "$client_node" ]; then

    if IFS=$'\t' read -r cilium_pod cilium_node cilium_endpoint < <(
      kubectl -n kube-system get pods -l k8s-app=cilium \
        -o jsonpath='{range .items[?(@.status.phase=="Running")]}{.metadata.name}{"\t"}{.spec.nodeName}{"\t"}{.status.podIP}{"\n"}{end}' \
        2>/dev/null \
        | awk -F $'\t' -v node="$client_node" '$2 == node {print; exit}'
    ) && [ -n "$cilium_endpoint" ]; then

      if IFS=$'\t' read -r collector_pod _ < <(
        kubectl -n acns-telemetry get pods -l app=acns-log-collector \
          -o jsonpath='{range .items[?(@.status.phase=="Running")]}{.metadata.name}{"\t"}{.spec.nodeName}{"\n"}{end}' \
          2>/dev/null \
          | awk -F $'\t' -v node="$client_node" '$2 == node {print; exit}'
      ) && [ -n "$collector_pod" ]; then

        last_endpoint="http://${cilium_endpoint}:9965/metrics from ${cilium_pod} on ${client_node} (acns-client=${client_pod}) via ${collector_pod}"
        if last_metrics=$(kubectl -n acns-telemetry exec "$collector_pod" \
            -c collector -- wget -q -T 5 -O - \
            "http://${cilium_endpoint}:9965/metrics" 2>&1); then
          last_probe_error=""
          if grep -Eq '^(# (HELP|TYPE) )?hubble_dns_queries_total([ {]|$)' \
              <<<"$last_metrics" &&
             grep -Eq '^(# (HELP|TYPE) )?hubble_dns_responses_total([ {]|$)' \
              <<<"$last_metrics"; then
            echo "ACNS telemetry is configured and DNS metric families are available from $last_endpoint."
            exit 0
          fi
          last_probe_error="Hubble endpoint responded without both DNS metric families"
        else
          last_probe_error="$last_metrics"
          last_metrics=""
        fi
      else
        last_probe_error="No Running acns-log-collector Pod found on acns-client node ${client_node} (acns-client=${client_pod})"
      fi
    else
      last_probe_error="No Running Cilium Pod found on acns-client node ${client_node} (acns-client=${client_pod})"
    fi
  else
    last_probe_error="No Running acns-client Pod found in acns-telemetry namespace"
  fi

  if [ "$(date +%s)" -ge "$metric_deadline" ]; then
    break
  fi
  sleep "$metric_poll_seconds"
done

echo "Timed out waiting for hubble_dns_queries_total and hubble_dns_responses_total from a real Hubble endpoint." >&2
echo "Last endpoint probe: $last_endpoint" >&2
echo "Last probe result: ${last_probe_error:-unknown failure}" >&2
if [ -n "$last_metrics" ]; then
  echo "Hubble metric families observed at the last endpoint:" >&2
  sed -n 's/^# TYPE \(hubble_[^ ]*\).*/\1/p' <<<"$last_metrics" \
    | sort -u | head -100 >&2
fi
kubectl get containernetworkmetric container-network-metric -o yaml >&2 || true
kubectl describe containernetworkmetric container-network-metric >&2 || true
kubectl -n acns-telemetry get pods -l app=acns-client -o wide >&2 || true
kubectl -n kube-system get pods -l k8s-app=cilium -o wide >&2 || true
kubectl -n acns-telemetry get pods -l app=acns-log-collector -o wide >&2 || true
exit 1
