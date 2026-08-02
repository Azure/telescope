#!/usr/bin/env bash
set -euo pipefail

enabled="${CL2_ACNS_TELEMETRY_ENABLED:-false}"
if [ "${enabled,,}" != "true" ]; then
  exit 0
fi

: "${KUBECONFIG:?KUBECONFIG is required}"
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
verify_only="${ACNS_VERIFY_ONLY:-false}"
timeout_seconds="${CL2_ACNS_SETUP_TIMEOUT_SECONDS:-600}"
metric_ready_timeout_seconds="${CL2_ACNS_METRIC_READY_TIMEOUT_SECONDS:-180}"
metric_poll_seconds="${CL2_ACNS_METRIC_POLL_SECONDS:-10}"
metric_probe_settle_seconds="${CL2_ACNS_METRIC_PROBE_SETTLE_SECONDS:-2}"
metric_min_delta="${CL2_ACNS_METRIC_MIN_DELTA:-1}"
traffic_burst_count="${CL2_ACNS_TRAFFIC_BURST_COUNT:-3}"
readiness_output="${ACNS_READINESS_OUTPUT:-}"
deadline=$(( $(date +%s) + timeout_seconds ))

for value_name in metric_probe_settle_seconds metric_min_delta traffic_burst_count; do
  value="${!value_name}"
  if ! [[ "$value" =~ ^[0-9]+$ ]]; then
    echo "$value_name must be a non-negative integer, got $value" >&2
    exit 1
  fi
done

metric_sum() {
  local metric_name="$1"
  local label_filter="${2:-}"
  awk -v metric="$metric_name" -v label_filter="$label_filter" '
    $1 == metric || index($1, metric "{") == 1 {
      if ((label_filter == "" || index($0, label_filter) > 0) &&
          $NF ~ /^[-+]?([0-9]+([.][0-9]*)?|[.][0-9]+)([eE][-+]?[0-9]+)?$/) {
        total += $NF
      }
    }
    END { printf "%.17g\n", total + 0 }
  '
}

metric_delta_meets_minimum() {
  local before="$1" after="$2"
  awk -v before="$before" -v after="$after" -v minimum="$metric_min_delta" \
    'BEGIN { exit !((after - before) >= minimum) }'
}

write_readiness() {
  local ready="$1" reason="$2" endpoint="$3" client="$4"
  local policy_mode="$5" query_before="$6" query_after="$7"
  local response_before="$8" response_after="$9"
  local accepted_gap="${10:-false}"
  [ -n "$readiness_output" ] || return 0
  mkdir -p "$(dirname "$readiness_output")"
  jq -n \
    --arg observed_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    --arg reason "$reason" \
    --arg endpoint "$endpoint" \
    --arg client_pod "$client" \
    --arg cilium_policy_mode "$policy_mode" \
    --argjson ready "$ready" \
    --argjson accepted_gap "$accepted_gap" \
    --argjson query_before "$query_before" \
    --argjson query_after "$query_after" \
    --argjson response_before "$response_before" \
    --argjson response_after "$response_after" \
    '{
      schema_version: 1,
      observed_at: $observed_at,
      ready: $ready,
      accepted_gap: $accepted_gap,
      reason: $reason,
      endpoint: $endpoint,
      client_pod: $client_pod,
      cilium_policy_mode: $cilium_policy_mode,
      counters: {
        hubble_dns_queries_total: {
          before: $query_before,
          after: $query_after,
          delta: ($query_after - $query_before)
        },
        hubble_dns_responses_total: {
          before: $response_before,
          after: $response_after,
          delta: ($response_after - $response_before)
        }
      }
    }' > "${readiness_output}.tmp"
  mv "${readiness_output}.tmp" "$readiness_output"
}

if [ "${verify_only,,}" != "true" ]; then
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
fi

cilium_policy_mode=$(kubectl -n kube-system get configmap cilium-config \
  -o jsonpath='{.data.enable-policy}' 2>/dev/null || true)
if [ "$cilium_policy_mode" = "never" ]; then
  reason="Cilium policy enforcement is disabled (cilium-config enable-policy=never); fresh DNS L7 metrics cannot be trusted"
  if [ "${CL2_ACCEPT_CILIUM_POLICY_GAP:-false}" = "true" ]; then
    reason="$reason; accepted by deadline policy"
    write_readiness false "$reason" "unavailable" "" \
      "$cilium_policy_mode" 0 0 0 0 true
    echo "$reason"
    exit 0
  fi
  write_readiness false "$reason" "unavailable" "" \
    "$cilium_policy_mode" 0 0 0 0 false
  echo "$reason" >&2
  exit 1
fi

metric_deadline=$(( $(date +%s) + metric_ready_timeout_seconds ))
last_endpoint="unavailable"
last_probe_error="no Running acns-client Pod found in acns-telemetry namespace"
last_metrics=""
last_query_before=0
last_query_after=0
last_response_before=0
last_response_after=0
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
          current_client_label="source=\"acns-telemetry/${client_pod}\""
          last_query_before=$(metric_sum \
            hubble_dns_queries_total "$current_client_label" <<<"$last_metrics")
          last_response_before=$(metric_sum hubble_dns_responses_total <<<"$last_metrics")

          probe_label=$(printf '%s-%s' "$client_pod" "$(date +%s%N)" \
            | tr -c '[:alnum:]-' '-')
          kubectl -n acns-telemetry exec "$client_pod" -c client -- sh -c "
            i=0
            while [ \"\$i\" -lt $traffic_burst_count ]; do
              nslookup \"\${i}.${probe_label}.invalid\" >/dev/null 2>&1 || true
              i=\$((i + 1))
            done
          " >/dev/null 2>&1 || true
          if [ "$metric_probe_settle_seconds" -gt 0 ]; then
            sleep "$metric_probe_settle_seconds"
          fi

          if last_metrics=$(kubectl -n acns-telemetry exec "$collector_pod" \
              -c collector -- wget -q -T 5 -O - \
              "http://${cilium_endpoint}:9965/metrics" 2>&1); then
            last_query_after=$(metric_sum \
              hubble_dns_queries_total "$current_client_label" <<<"$last_metrics")
            last_response_after=$(metric_sum hubble_dns_responses_total <<<"$last_metrics")
            if grep -Fq "$current_client_label" <<<"$last_metrics" &&
               metric_delta_meets_minimum "$last_query_before" "$last_query_after" &&
               metric_delta_meets_minimum "$last_response_before" "$last_response_after"; then
              write_readiness true "fresh DNS counters advanced" "$last_endpoint" \
                "$client_pod" "$cilium_policy_mode" \
                "$last_query_before" "$last_query_after" \
                "$last_response_before" "$last_response_after"
              echo "ACNS telemetry is configured and fresh DNS counters advanced from $last_endpoint."
              exit 0
            fi
            last_probe_error="Hubble DNS counters did not advance for the current acns-client Pod"
          else
            last_probe_error="$last_metrics"
            last_metrics=""
          fi
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
echo "Last DNS counters: queries=${last_query_before}->${last_query_after}, responses=${last_response_before}->${last_response_after}" >&2
write_readiness false "${last_probe_error:-unknown failure}" "$last_endpoint" \
  "${client_pod:-}" "$cilium_policy_mode" \
  "$last_query_before" "$last_query_after" \
  "$last_response_before" "$last_response_after"
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
