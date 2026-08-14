#!/usr/bin/env bash
set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=managed-prometheus-common.sh
source "$script_dir/managed-prometheus-common.sh"

if ! managed_telemetry_enabled; then
  echo "AKS control-plane managed Prometheus is disabled; skipping ingestion wait."
  exit 0
fi

initialize_managed_telemetry

platform_metric_names=(
  apiserver_cpu_usage_percentage
  apiserver_memory_usage_percentage
  etcd_cpu_usage_percentage
  etcd_memory_usage_percentage
)
platform_metrics_required="${AKS_PLATFORM_METRICS_REQUIRED:-false}"
platform_wait_when_optional="${AKS_PLATFORM_METRICS_WAIT_WHEN_OPTIONAL:-false}"
platform_window_coverage_required="${AKS_PLATFORM_METRICS_REQUIRE_WINDOW_COVERAGE:-false}"
platform_coverage_grace_seconds="${AKS_PLATFORM_METRICS_COVERAGE_GRACE_SECONDS:-300}"
platform_min_coverage_percent="${AKS_PLATFORM_METRICS_MIN_COVERAGE_PERCENT:-0}"
if ! [[ "$platform_coverage_grace_seconds" =~ ^[0-9]+$ ]]; then
  echo "AKS_PLATFORM_METRICS_COVERAGE_GRACE_SECONDS must be a non-negative integer." >&2
  exit 1
fi
if ! [[ "$platform_min_coverage_percent" =~ ^[0-9]+$ ]] ||
   [ "$platform_min_coverage_percent" -gt 100 ]; then
  echo "AKS_PLATFORM_METRICS_MIN_COVERAGE_PERCENT must be an integer from 0 to 100." >&2
  exit 1
fi
platform_window_start="$configured_at"
platform_window_end=""
if [ -n "${SHARE_INFRA_META:-}" ] && [ -s "$SHARE_INFRA_META" ]; then
  platform_window_start=$(jq -r \
    '[.[] | .start_timestamp // empty] | min // empty' \
    "$SHARE_INFRA_META")
  platform_window_end=$(jq -r \
    '[.[] | .end_timestamp // empty] | max // empty' \
    "$SHARE_INFRA_META")
fi
if [ -z "$platform_window_start" ]; then
  platform_window_start="$configured_at"
fi

wait_for_platform_metrics() {
  local timeout="${AKS_PLATFORM_METRICS_TIMEOUT_SECONDS:-3600}"
  local deadline=$(( $(date +%s) + timeout ))
  local missing role cluster_id available remaining sleep_seconds response
  local required_start_epoch required_end_epoch expected_samples minimum_samples
  required_start_epoch=$(date -u -d "$platform_window_start" +%s)
  required_end_epoch=0
  if [ -n "$platform_window_end" ]; then
    required_end_epoch=$(date -u -d "$platform_window_end" +%s)
  elif [ "${platform_window_coverage_required,,}" = "true" ]; then
    echo "Required platform metric window coverage cannot be evaluated because no scenario end timestamp is available." >&2
    return 1
  fi
  expected_samples=1
  minimum_samples=1
  if [ "$required_end_epoch" -gt "$required_start_epoch" ]; then
    expected_samples=$(( (required_end_epoch - required_start_epoch) / 60 + 1 ))
    minimum_samples=$(( \
      (expected_samples * platform_min_coverage_percent + 99) / 100 ))
    if [ "$minimum_samples" -lt 1 ]; then
      minimum_samples=1
    fi
  fi
  while [ "$(date +%s)" -lt "$deadline" ]; do
    missing=0
    while IFS= read -r cluster; do
      role=$(echo "$cluster" | jq -r '.role')
      cluster_id=$(echo "$cluster" | jq -r '.id')
      response=$(az monitor metrics list \
        --resource "$cluster_id" \
        --metrics "${platform_metric_names[@]}" \
        --interval PT1M \
        --aggregation Average \
        --start-time "$configured_at" \
        --end-time "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
        -o json 2>/dev/null || echo '{"value":[]}')
      if [ "${platform_window_coverage_required,,}" = "true" ] &&
         [ "$required_end_epoch" -gt 0 ]; then
        available=$(jq \
          --argjson required_start "$required_start_epoch" \
          --argjson required_end "$required_end_epoch" \
          --argjson grace "$platform_coverage_grace_seconds" \
          --argjson minimum_samples "$minimum_samples" \
          '[
            .value[]
            | [
                .timeseries[].data[]?
                | select(.average != null)
                | (
                    try (
                      .timeStamp
                      | .[0:19] + "Z"
                      | fromdateiso8601
                    )
                    catch empty
                  )
              ] as $timestamps
            | select(
                ($timestamps | length) > 0
                and ($timestamps | unique | length) >= $minimum_samples
                and ($timestamps | min) <= ($required_start + $grace)
                and ($timestamps | max) >= ($required_end - $grace)
              )
          ] | length' <<<"$response" 2>/dev/null || echo 0)
      else
        available=$(jq \
          '[.value[] | select(any(.timeseries[].data[]?; .average != null))] | length' \
          <<<"$response" 2>/dev/null || echo 0)
      fi
      if [ "${available:-0}" -ne "${#platform_metric_names[@]}" ]; then
        echo "[$role] waiting for platform CPU/memory metrics ($available/${#platform_metric_names[@]}) window=${platform_window_start}..${platform_window_end:-current} minimum_samples=$minimum_samples"
        missing=$((missing + 1))
      fi
    done < <(jq -c '.clusters[]' "$MANIFEST_PATH")
    if [ "$missing" -eq 0 ]; then
      return 0
    fi
    remaining=$((deadline - $(date +%s)))
    if [ "$remaining" -le 0 ]; then
      break
    fi
    sleep_seconds=60
    if [ "$sleep_seconds" -gt "$remaining" ]; then
      sleep_seconds=$remaining
    fi
    sleep "$sleep_seconds"
  done
  return 1
}

platform_wait_enabled=false
if [ "${platform_metrics_required,,}" = "true" ] ||
   [ "${platform_wait_when_optional,,}" = "true" ]; then
  platform_wait_enabled=true
fi
platform_metrics_ready=false
if [ "$platform_wait_enabled" = "true" ]; then
  platform_wait_rc=0
  wait_for_platform_metrics || platform_wait_rc=$?
  if [ "$platform_wait_rc" -eq 0 ]; then
    platform_metrics_ready=true
  elif [ "${platform_metrics_required,,}" = "true" ]; then
    echo "##vso[task.logissue type=error;] Required AKS platform CPU/memory metrics did not cover the scenario window before timeout; exporting every available platform metric anyway."
  else
    echo "##vso[task.logissue type=warning;] AKS platform CPU/memory metrics did not appear before timeout; exporting every available platform metric anyway."
  fi
else
  echo "AKS platform CPU/memory metrics are optional; skipping the ingestion wait and exporting any available samples."
fi
end_time=$(date -u +%Y-%m-%dT%H:%M:%SZ)

wait_for_managed_prometheus() {
  local timeout="${AKS_MANAGED_PROMETHEUS_TIMEOUT_SECONDS:-3600}"
  local poll_seconds="${AKS_MANAGED_PROMETHEUS_POLL_SECONDS:-60}"
  local deadline=$(( $(date +%s) + timeout ))
  local expected_count remaining command_timeout sleep_seconds token
  local response available query role cluster_alias query_endpoint resource_scope
  local readiness_jsonl ready workspace_name request_timeout timed_out
  expected_count=$(jq '.clusters | length' "$MANIFEST_PATH")

  while [ "$(date +%s)" -lt "$deadline" ]; do
    remaining=$((deadline - $(date +%s)))
    if [ "$remaining" -le 0 ]; then
      break
    fi
    command_timeout=$remaining
    if [ "$command_timeout" -gt 120 ]; then
      command_timeout=120
    fi
    token=$(timeout "${command_timeout}s" az account get-access-token \
      --resource https://prometheus.monitor.azure.com \
      --query accessToken -o tsv 2>/dev/null || true)
    readiness_jsonl=$(mktemp)
    available=0
    timed_out=false
    if [ -n "$token" ]; then
      while IFS= read -r cluster; do
        remaining=$((deadline - $(date +%s)))
        if [ "$remaining" -le 0 ]; then
          timed_out=true
          break
        fi
        request_timeout=$remaining
        if [ "$request_timeout" -gt 120 ]; then
          request_timeout=120
        fi
        role=$(echo "$cluster" | jq -r '.role')
        cluster_alias=$(echo "$cluster" | jq -r '.prometheus_cluster_alias')
        query_endpoint=$(echo "$cluster" | jq -r '.workspace.prometheus_query_endpoint')
        workspace_name=$(echo "$cluster" | jq -r '.workspace.name')
        if [ -z "$query_endpoint" ] || [ "$query_endpoint" = "null" ]; then
          query_endpoint=$(jq -r \
            '.workspace.prometheus_query_endpoint // .query.resource_endpoint' \
            "$MANIFEST_PATH")
          workspace_name=$(jq -r '.workspace.name // "legacy"' "$MANIFEST_PATH")
        fi
        resource_scope=$(echo "$cluster" | jq -r '.id')
        query="count(apiserver_request_total{cluster=\"$cluster_alias\"})"
        response=$(curl -fsS -G "$query_endpoint/api/v1/query_range" \
          --connect-timeout 10 \
          --max-time "$request_timeout" \
          -H "Authorization: Bearer $token" \
          -H "x-ms-azure-scoping: $resource_scope" \
          --data-urlencode "query=$query" \
          --data-urlencode "start=$configured_at" \
          --data-urlencode "end=$end_time" \
          --data-urlencode "step=60s" \
          2>/dev/null || true)
        if [ -z "$response" ]; then
          response='{}'
        fi
        ready=$(printf '%s' "$response" | jq -r \
          'any(.data.result[]?; ((.values // []) | length) > 0)' \
          2>/dev/null || echo false)
        if [ "$ready" = "true" ]; then
          available=$((available + 1))
        else
          ready=false
        fi
        jq -cn \
          --arg role "$role" \
          --arg workspace "$workspace_name" \
          --argjson ready "$ready" \
          '{role: $role, workspace: $workspace, ready: $ready}' \
          >> "$readiness_jsonl"
      done < <(jq -c '.clusters[]' "$MANIFEST_PATH")
    fi
    managed_readiness=$(jq -s '.' "$readiness_jsonl")
    rm -f "$readiness_jsonl"
    if [ "$timed_out" = "true" ]; then
      break
    fi
    if [ "$available" -eq "$expected_count" ]; then
      echo "Managed Prometheus samples are available for all $expected_count clusters."
      return 0
    fi
    echo "Waiting for managed Prometheus samples ($available/$expected_count clusters)..."
    remaining=$((deadline - $(date +%s)))
    if [ "$remaining" -le 0 ]; then
      break
    fi
    sleep_seconds=$poll_seconds
    if [ "$sleep_seconds" -gt "$remaining" ]; then
      sleep_seconds=$remaining
    fi
    if [ "$sleep_seconds" -gt 0 ]; then
      sleep "$sleep_seconds"
    fi
  done
  return 1
}

managed_prometheus_ready=false
managed_readiness='[]'
managed_wait_rc=0
wait_for_managed_prometheus || managed_wait_rc=$?
if [ "$managed_wait_rc" -eq 0 ]; then
  managed_prometheus_ready=true
else
  echo "##vso[task.logissue type=warning;] Managed Prometheus samples did not appear for every cluster before timeout; manifests and live-coupled platform artifacts will still be preserved."
fi

capacity_end=$(date -u +%Y-%m-%dT%H:%M:%SZ)
capacity_audits_jsonl=$(mktemp)
managed_prometheus_throttled=false
amw_capacity_verified=true
while IFS= read -r workspace; do
  workspace_slot=$(echo "$workspace" | jq -r '.slot // .name')
  workspace_id=$(echo "$workspace" | jq -r '.id')
  capacity_window_start=$(echo "$workspace" | jq -r \
    '.capacity_guard.monitoring_window_start // empty')
  if [ -z "$capacity_window_start" ]; then
    capacity_window_start="$configured_at"
  fi
  workspace_dir="$OUTPUT_DIR/workspace-${workspace_slot}"
  mkdir -p "$workspace_dir"
  capacity_raw="$workspace_dir/amw-capacity.json"
  capacity_summary="$workspace_dir/amw-capacity-summary.json"
  capacity_status=0
  if ! capture_amw_capacity \
      "$workspace_id" \
      "$capacity_window_start" \
      "$capacity_end" \
      "$capacity_raw" \
      "$capacity_summary"; then
    capacity_status=1
  else
    amw_capacity_runtime_ok "$capacity_summary" || capacity_status=$?
  fi
  if [ -s "$capacity_summary" ]; then
    write_amw_capacity_markdown \
      "$capacity_summary" \
      "$workspace_dir/amw-capacity-summary.md"
  fi
  if [ "$capacity_status" -eq 1 ]; then
    amw_capacity_verified=false
  elif [ "$capacity_status" -eq 2 ]; then
    managed_prometheus_throttled=true
    managed_prometheus_ready=false
  fi
  jq -cn \
    --arg slot "$workspace_slot" \
    --argjson status "$capacity_status" \
    --slurpfile summary "$capacity_summary" \
    '{slot: $slot, status: $status, summary: ($summary[0] // {})}' \
    >> "$capacity_audits_jsonl"
done < <(echo "$workspaces_json" | jq -c '.[]')
capacity_audits=$(jq -s '.' "$capacity_audits_jsonl")
rm -f "$capacity_audits_jsonl"

start_epoch=$(date -u -d "$configured_at" +%s)
end_epoch=$(date -u -d "$end_time" +%s)
max_series_window_seconds=$((12 * 60 * 60 - 60))
if [ $((end_epoch - start_epoch)) -gt "$max_series_window_seconds" ]; then
  audit_start_epoch=$((end_epoch - max_series_window_seconds))
  audit_start=$(date -u -d "@$audit_start_epoch" +%Y-%m-%dT%H:%M:%SZ)
else
  audit_start="$configured_at"
fi

collection_manifest_tmp="${collection_manifest}.tmp"
scenario_windows='[]'
platform_window_coverage_required_json=false
if [ "${platform_window_coverage_required,,}" = "true" ]; then
  platform_window_coverage_required_json=true
fi
platform_wait_enabled_json=false
if [ "$platform_wait_enabled" = "true" ]; then
  platform_wait_enabled_json=true
fi
if [ -n "${SHARE_INFRA_META:-}" ] &&
   [ -s "$SHARE_INFRA_META" ]; then
  scenario_windows=$(cat "$SHARE_INFRA_META")
fi
managed_readiness_file=$(mktemp)
capacity_audits_file=$(mktemp)
scenario_windows_file=$(mktemp)
printf '%s' "$managed_readiness" >"$managed_readiness_file"
printf '%s' "$capacity_audits" >"$capacity_audits_file"
printf '%s' "$scenario_windows" >"$scenario_windows_file"
jq \
  --arg collected_at "$end_time" \
  --arg audit_window_start "$audit_start" \
  --arg audit_window_end "$end_time" \
  --argjson platform_metrics_ready "$platform_metrics_ready" \
  --argjson managed_prometheus_ready "$managed_prometheus_ready" \
  --argjson managed_prometheus_throttled "$managed_prometheus_throttled" \
  --argjson amw_capacity_verified "$amw_capacity_verified" \
  --slurpfile managed_readiness_arr "$managed_readiness_file" \
  --slurpfile capacity_audits_arr "$capacity_audits_file" \
  --slurpfile scenario_windows_arr "$scenario_windows_file" \
  --arg platform_window_start "$platform_window_start" \
  --arg platform_window_end "$platform_window_end" \
  --argjson platform_wait_enabled "$platform_wait_enabled_json" \
  --argjson platform_window_coverage_required \
    "$platform_window_coverage_required_json" \
  --argjson platform_min_coverage_percent "$platform_min_coverage_percent" \
  '($managed_readiness_arr[0]) as $managed_readiness |
  ($capacity_audits_arr[0]) as $capacity_audits |
  ($scenario_windows_arr[0]) as $scenario_windows |
  . + {
    collected_at: $collected_at,
    platform_metrics_ready: $platform_metrics_ready,
    managed_prometheus_ready: $managed_prometheus_ready,
    managed_prometheus_throttled: $managed_prometheus_throttled,
    amw_capacity_verified: $amw_capacity_verified,
    managed_readiness: $managed_readiness,
    capacity_audits: $capacity_audits,
    scenario_windows: $scenario_windows,
    platform_metrics_window: {
      start: $platform_window_start,
      end: (
        if ($platform_window_end | length) > 0
        then $platform_window_end
        else null
        end
      ),
      wait_enabled: $platform_wait_enabled,
      full_window_required: $platform_window_coverage_required,
      minimum_coverage_percent: $platform_min_coverage_percent
    },
    audit_window: {
      start: $audit_window_start,
      end: $audit_window_end
    },
    logs_window: {
      start: .configured_at,
      end: null,
      deferred: true
    }
  }' "$MANIFEST_PATH" > "$collection_manifest_tmp"
mv "$collection_manifest_tmp" "$collection_manifest"
rm -f \
  "$managed_readiness_file" \
  "$capacity_audits_file" \
  "$scenario_windows_file"

echo "Managed telemetry collection window: $audit_start .. $end_time"
amw_capacity_ok=false
if [ "$managed_prometheus_throttled" = "false" ] &&
   [ "$amw_capacity_verified" = "true" ]; then
  amw_capacity_ok=true
fi
echo "##vso[task.setvariable variable=AKS_TELEMETRY_WINDOW_READY]true"
echo "##vso[task.setvariable variable=AKS_MANAGED_PROMETHEUS_READY]$managed_prometheus_ready"
echo "##vso[task.setvariable variable=AKS_AMW_CAPACITY_OK]$amw_capacity_ok"
if [ "${platform_metrics_required,,}" = "true" ] &&
   [ "$platform_metrics_ready" != "true" ]; then
  exit 1
fi
