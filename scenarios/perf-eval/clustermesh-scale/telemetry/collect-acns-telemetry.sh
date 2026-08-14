#!/usr/bin/env bash
set -euo pipefail

enabled="${CL2_ACNS_TELEMETRY_ENABLED:-false}"
if [ "${enabled,,}" != "true" ]; then
  exit 0
fi

: "${KUBECONFIG:?KUBECONFIG is required}"
: "${OUTPUT_DIR:?OUTPUT_DIR is required}"
mkdir -p "$OUTPUT_DIR"
window_start="${ACNS_WINDOW_START_TIMESTAMP:-}"
archive_attempts="${CL2_ACNS_ARCHIVE_ATTEMPTS:-3}"
archive_retry_seconds="${CL2_ACNS_ARCHIVE_RETRY_SECONDS:-5}"
if ! [[ "$archive_attempts" =~ ^[1-9][0-9]*$ ]]; then
  echo "CL2_ACNS_ARCHIVE_ATTEMPTS must be a positive integer." >&2
  exit 1
fi
if ! [[ "$archive_retry_seconds" =~ ^[0-9]+$ ]]; then
  echo "CL2_ACNS_ARCHIVE_RETRY_SECONDS must be a non-negative integer." >&2
  exit 1
fi

kubectl get containernetworklog clustermesh-scale-acns -o json \
  > "$OUTPUT_DIR/container-network-log.json"
metric_config_captured=true
if ! kubectl get containernetworkmetric container-network-metric -o json \
    > "$OUTPUT_DIR/container-network-metric.json"; then
  metric_config_captured=false
  printf '%s\n' '{"error":"ContainerNetworkMetric resource unavailable during collection"}' \
    > "$OUTPUT_DIR/container-network-metric.json"
  echo "ContainerNetworkMetric resource unavailable during ACNS collection." >&2
fi
kubectl -n acns-telemetry get pods -o wide \
  > "$OUTPUT_DIR/pods.txt"
kubectl -n acns-telemetry logs deployment/acns-client --tail=500 \
  > "$OUTPUT_DIR/client.log" 2>&1 || true

collector_pods_json=$(kubectl -n acns-telemetry get pods \
  -l app=acns-log-collector \
  -o json)
expected_archive_count=$(echo "$collector_pods_json" | jq '.items | length')
archives_jsonl=$(mktemp)
nonempty_log_archives=0
fresh_event_archives=0
while IFS=$'\t' read -r pod node; do
  [ -n "$pod" ] || continue
  safe_node=$(printf '%s' "$node" | sed -E 's/[^a-zA-Z0-9_.-]+/_/g')
  archive="$OUTPUT_DIR/cnl-${safe_node}.tar.gz"
  partial="${archive}.partial"
  archive_ok=false
  for attempt in $(seq 1 "$archive_attempts"); do
    rm -f "$partial"
    if kubectl -n acns-telemetry exec "$pod" -c collector -- \
        tar czf - -C /host-acns . > "$partial" 2>/dev/null &&
       gzip -t "$partial" 2>/dev/null &&
       tar -tzf "$partial" >/dev/null 2>&1; then
      archive_ok=true
      break
    fi
    echo "ACNS archive attempt $attempt/$archive_attempts failed for $pod on $node." >&2
    if [ "$attempt" -lt "$archive_attempts" ] &&
       [ "$archive_retry_seconds" -gt 0 ]; then
      sleep "$archive_retry_seconds"
    fi
  done
  if [ "$archive_ok" = "true" ]; then
    mv "$partial" "$archive"
    size=$(stat -c%s "$archive")
    contains_events=false
    event_member=$(tar -tzf "$archive" \
      | grep -E '(^|/)events\.log$' \
      | head -1 || true)
    event_bytes=0
    current_window_event_count=0
    if [ -n "$event_member" ]; then
      event_bytes=$(tar -xOzf "$archive" "$event_member" 2>/dev/null \
        | wc -c)
      if [ -n "$window_start" ]; then
        current_window_event_count=$(tar -xOzf \
          "$archive" "$event_member" 2>/dev/null \
          | jq -c --arg start "$window_start" \
            'select((.time // .flow.time // "") >= $start)' \
            2>/dev/null \
          | wc -l)
      fi
    fi
    if [ "$event_bytes" -gt 0 ]; then
      contains_events=true
      nonempty_log_archives=$((nonempty_log_archives + 1))
    fi
    if [ "$current_window_event_count" -gt 0 ]; then
      fresh_event_archives=$((fresh_event_archives + 1))
    fi
    jq -cn \
      --arg pod "$pod" \
      --arg node "$node" \
      --arg file "$(basename "$archive")" \
      --argjson bytes "$size" \
      --argjson contains_events "$contains_events" \
      --argjson current_window_event_count "$current_window_event_count" \
      '{
        pod: $pod,
        node: $node,
        file: $file,
        bytes: $bytes,
        contains_events: $contains_events,
        current_window_event_count: $current_window_event_count
      }' \
      >> "$archives_jsonl"
  else
    rm -f "$partial"
  fi
done < <(echo "$collector_pods_json" \
  | jq -r '.items[] | [.metadata.name, .spec.nodeName] | @tsv')

archives=$(jq -s '.' "$archives_jsonl")
rm -f "$archives_jsonl"
archive_count=$(echo "$archives" | jq 'length')
complete=false
if [ "$expected_archive_count" -gt 0 ] &&
   [ "$archive_count" -eq "$expected_archive_count" ] &&
   [ "$nonempty_log_archives" -gt 0 ] &&
   { [ -z "$window_start" ] || [ "$fresh_event_archives" -gt 0 ]; } &&
   [ "$metric_config_captured" = "true" ]; then
  complete=true
fi
jq -n \
  --arg collected_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --arg window_start "$window_start" \
  --argjson complete "$complete" \
  --argjson expected_archives "$expected_archive_count" \
  --argjson nonempty_log_archives "$nonempty_log_archives" \
  --argjson fresh_event_archives "$fresh_event_archives" \
  --argjson metric_config_captured "$metric_config_captured" \
  --argjson archives "$archives" \
  '{
    schema_version: 1,
    collected_at: $collected_at,
    window_start: (if ($window_start | length) > 0 then $window_start else null end),
    complete: $complete,
    expected_archives: $expected_archives,
    nonempty_log_archives: $nonempty_log_archives,
    fresh_event_archives: $fresh_event_archives,
    metric_config_captured: $metric_config_captured,
    archives: $archives
  }' > "$OUTPUT_DIR/summary.json"

kubectl delete containernetworklog clustermesh-scale-acns \
  --ignore-not-found >/dev/null 2>&1 || true
kubectl delete containernetworkmetric container-network-metric \
  --ignore-not-found >/dev/null 2>&1 || true
kubectl delete namespace acns-telemetry \
  --ignore-not-found --wait=false >/dev/null 2>&1 || true

if [ "$complete" != "true" ]; then
  echo "ACNS host log collection incomplete: expected=$expected_archive_count collected=$archive_count nonempty=$nonempty_log_archives fresh=$fresh_event_archives window_start=${window_start:-not-required}" >&2
  exit 1
fi

echo "Collected $archive_count ACNS host log archive(s) into $OUTPUT_DIR."
