#!/usr/bin/env bash

managed_telemetry_enabled() {
  local enabled="${AKS_CONTROL_PLANE_METRICS_ENABLED:-false}"
  [ "${enabled,,}" = "true" ]
}

capture_amw_capacity() {
  local resource_id="${1:?AMW resource ID is required}"
  local start_time="${2:?AMW capacity start time is required}"
  local end_time="${3:?AMW capacity end time is required}"
  local raw_output="${4:?AMW capacity raw output path is required}"
  local summary_output="${5:?AMW capacity summary output path is required}"
  local attempts="${AKS_AMW_METRICS_QUERY_ATTEMPTS:-3}"
  local retry_seconds="${AKS_AMW_METRICS_QUERY_RETRY_SECONDS:-5}"
  local attempt capacity_file drops_file raw_tmp summary_tmp

  if ! [[ "$attempts" =~ ^[1-9][0-9]*$ ]]; then
    echo "AKS_AMW_METRICS_QUERY_ATTEMPTS must be a positive integer." >&2
    return 1
  fi
  if ! [[ "$retry_seconds" =~ ^[0-9]+$ ]]; then
    echo "AKS_AMW_METRICS_QUERY_RETRY_SECONDS must be a non-negative integer." >&2
    return 1
  fi

  mkdir -p "$(dirname "$raw_output")" "$(dirname "$summary_output")"
  capacity_file=$(mktemp)
  drops_file=$(mktemp)
  raw_tmp="${raw_output}.tmp"
  summary_tmp="${summary_output}.tmp"

  for ((attempt = 1; attempt <= attempts; attempt++)); do
    if az monitor metrics list \
        --resource "$resource_id" \
        --metrics \
          ActiveTimeSeries \
          ActiveTimeSeriesLimit \
          ActiveTimeSeriesPercentUtilization \
          EventsPerMinuteIngested \
          EventsPerMinuteIngestedLimit \
          EventsPerMinuteIngestedPercentUtilization \
        --interval PT1M \
        --aggregation Maximum \
        --start-time "$start_time" \
        --end-time "$end_time" \
        -o json > "$capacity_file" &&
       az monitor metrics list \
        --resource "$resource_id" \
        --metrics TimeSeriesSamplesDropped EventsDropped \
        --filter "Reason eq '*'" \
        --interval PT1M \
        --aggregation Total \
        --start-time "$start_time" \
        --end-time "$end_time" \
        -o json > "$drops_file"; then
      jq -n \
        --arg resource_id "$resource_id" \
        --arg start "$start_time" \
        --arg end "$end_time" \
        --slurpfile capacity "$capacity_file" \
        --slurpfile drops "$drops_file" \
        '{
          schema_version: 1,
          query_succeeded: true,
          resource_id: $resource_id,
          window: {start: $start, end: $end},
          capacity: $capacity[0],
          drops: $drops[0]
        }' > "$raw_tmp"

      jq '
        def values($metric):
          [.capacity.value[]?
            | select(.name.value == $metric)
            | .timeseries[]?.data[]?
            | (.maximum // .average // .total // empty)];
        def maximum($metric): (values($metric) | max // 0);
        def has_values($metric): ((values($metric) | length) > 0);
        ([.drops.value[]? as $metric
          | $metric.timeseries[]?
          | ((.metadatavalues // [])
              | map(select(.name.value == "Reason") | .value)
              | first // "Unknown") as $reason
          | {
              metric: $metric.name.value,
              reason: $reason,
              total: (
                [.data[]? | (.total // .average // .maximum // empty)]
                | add // 0
              )
            }]) as $drops
        | {
            schema_version: 1,
            query_succeeded: true,
            resource_id,
            window,
            capacity_samples: {
              active_series: has_values("ActiveTimeSeries"),
              active_series_limit: has_values("ActiveTimeSeriesLimit"),
              active_series_percent: has_values(
                "ActiveTimeSeriesPercentUtilization"
              ),
              events_per_minute: has_values("EventsPerMinuteIngested"),
              events_per_minute_limit: has_values(
                "EventsPerMinuteIngestedLimit"
              ),
              events_per_minute_percent: has_values(
                "EventsPerMinuteIngestedPercentUtilization"
              )
            },
            has_capacity_samples: (
              has_values("ActiveTimeSeries")
              or has_values("ActiveTimeSeriesLimit")
              or has_values("ActiveTimeSeriesPercentUtilization")
              or has_values("EventsPerMinuteIngested")
              or has_values("EventsPerMinuteIngestedLimit")
              or has_values("EventsPerMinuteIngestedPercentUtilization")
            ),
            capacity_samples_complete: (
              has_values("ActiveTimeSeries")
              and has_values("ActiveTimeSeriesLimit")
              and has_values("ActiveTimeSeriesPercentUtilization")
              and has_values("EventsPerMinuteIngested")
              and has_values("EventsPerMinuteIngestedLimit")
              and has_values("EventsPerMinuteIngestedPercentUtilization")
            ),
            active_series: {
              maximum: maximum("ActiveTimeSeries"),
              limit: maximum("ActiveTimeSeriesLimit"),
              maximum_percent: maximum(
                "ActiveTimeSeriesPercentUtilization"
              )
            },
            events_per_minute: {
              maximum_received: maximum("EventsPerMinuteIngested"),
              limit: maximum("EventsPerMinuteIngestedLimit"),
              maximum_percent: maximum(
                "EventsPerMinuteIngestedPercentUtilization"
              )
            },
            drops_by_reason: $drops,
            limit_throttling: {
              events_dropped: (
                [$drops[]
                  | select(
                      .metric == "EventsDropped"
                      and .reason == "LimitThrottling"
                    )
                  | .total]
                | add // 0
              ),
              time_series_samples_dropped: (
                [$drops[]
                  | select(
                      .metric == "TimeSeriesSamplesDropped"
                      and .reason == "LimitThrottling"
                    )
                  | .total]
                | add // 0
              )
            }
          }
        | .capacity_ok = (
            .capacity_samples_complete
            and .active_series.maximum_percent < 100
            and .events_per_minute.maximum_percent < 100
            and .limit_throttling.events_dropped == 0
            and .limit_throttling.time_series_samples_dropped == 0
          )' "$raw_tmp" > "$summary_tmp"

      mv "$raw_tmp" "$raw_output"
      mv "$summary_tmp" "$summary_output"
      rm -f "$capacity_file" "$drops_file"
      return 0
    fi

    echo "##vso[task.logissue type=warning;] Unable to query AMW capacity (attempt $attempt/$attempts)."
    if [ "$attempt" -lt "$attempts" ] && [ "$retry_seconds" -gt 0 ]; then
      sleep "$retry_seconds"
    fi
  done

  jq -n \
    --arg resource_id "$resource_id" \
    --arg start "$start_time" \
    --arg end "$end_time" \
    --arg error "Azure Monitor metrics query failed after $attempts attempt(s)" \
    '{
      schema_version: 1,
      query_succeeded: false,
      resource_id: $resource_id,
      window: {start: $start, end: $end},
      error: $error
    }' > "$raw_tmp"
  jq -n \
    --arg resource_id "$resource_id" \
    --arg start "$start_time" \
    --arg end "$end_time" \
    --arg error "Azure Monitor metrics query failed after $attempts attempt(s)" \
    '{
      schema_version: 1,
      query_succeeded: false,
      resource_id: $resource_id,
      window: {start: $start, end: $end},
      error: $error,
      capacity_samples: {
        active_series: false,
        active_series_limit: false,
        active_series_percent: false,
        events_per_minute: false,
        events_per_minute_limit: false,
        events_per_minute_percent: false
      },
      has_capacity_samples: false,
      capacity_samples_complete: false,
      active_series: {maximum: 0, limit: 0, maximum_percent: 0},
      events_per_minute: {
        maximum_received: 0,
        limit: 0,
        maximum_percent: 0
      },
      drops_by_reason: [],
      limit_throttling: {
        events_dropped: 0,
        time_series_samples_dropped: 0
      },
      capacity_ok: false
    }' > "$summary_tmp"
  mv "$raw_tmp" "$raw_output"
  mv "$summary_tmp" "$summary_output"
  rm -f "$capacity_file" "$drops_file"
  return 1
}

log_amw_capacity_summary() {
  local summary_path="${1:?AMW capacity summary path is required}"
  local active active_limit active_percent events events_limit events_percent
  local events_dropped samples_dropped

  active=$(jq -r '.active_series.maximum' "$summary_path")
  active_limit=$(jq -r '.active_series.limit' "$summary_path")
  active_percent=$(jq -r '.active_series.maximum_percent' "$summary_path")
  events=$(jq -r '.events_per_minute.maximum_received' "$summary_path")
  events_limit=$(jq -r '.events_per_minute.limit' "$summary_path")
  events_percent=$(jq -r '.events_per_minute.maximum_percent' "$summary_path")
  events_dropped=$(jq -r \
    '.limit_throttling.events_dropped' \
    "$summary_path")
  samples_dropped=$(jq -r \
    '.limit_throttling.time_series_samples_dropped' \
    "$summary_path")

  echo "AMW capacity: active_series=$active/$active_limit (${active_percent}%), events_per_minute=$events/$events_limit (${events_percent}%), limit_dropped_events=$events_dropped, limit_dropped_series_samples=$samples_dropped"
}

amw_capacity_preflight_ok() {
  local summary_path="${1:?AMW capacity summary path is required}"
  local threshold="${2:-${AKS_AMW_PREFLIGHT_MAX_UTILIZATION_PERCENT:-50}}"
  local query_succeeded has_samples samples_complete active_percent events_percent
  local events_dropped samples_dropped

  if ! [[ "$threshold" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
    echo "AKS_AMW_PREFLIGHT_MAX_UTILIZATION_PERCENT must be numeric." >&2
    return 1
  fi

  log_amw_capacity_summary "$summary_path"
  query_succeeded=$(jq -r '.query_succeeded' "$summary_path")
  if [ "$query_succeeded" != "true" ]; then
    echo "AMW capacity query did not succeed." >&2
    return 1
  fi
  has_samples=$(jq -r '.has_capacity_samples' "$summary_path")
  events_dropped=$(jq -r \
    '.limit_throttling.events_dropped' \
    "$summary_path")
  samples_dropped=$(jq -r \
    '.limit_throttling.time_series_samples_dropped' \
    "$summary_path")
  if awk -v events="$events_dropped" -v samples="$samples_dropped" \
      'BEGIN {exit !(events > 0 || samples > 0)}'; then
    echo "AMW reported recent LimitThrottling drops." >&2
    return 1
  fi
  if [ "$has_samples" != "true" ]; then
    echo "AMW has no recent capacity samples; treating the workspace as idle."
    return 0
  fi
  samples_complete=$(jq -r '.capacity_samples_complete' "$summary_path")
  if [ "$samples_complete" != "true" ]; then
    echo "AMW returned only partial capacity metrics; preflight cannot establish workspace headroom." >&2
    return 1
  fi

  active_percent=$(jq -r '.active_series.maximum_percent' "$summary_path")
  events_percent=$(jq -r '.events_per_minute.maximum_percent' "$summary_path")

  if awk -v value="$active_percent" -v limit="$threshold" \
      'BEGIN {exit !(value >= limit)}'; then
    echo "AMW active-series utilization ${active_percent}% is at or above the ${threshold}% preflight limit." >&2
    return 1
  fi
  if awk -v value="$events_percent" -v limit="$threshold" \
      'BEGIN {exit !(value >= limit)}'; then
    echo "AMW event-rate utilization ${events_percent}% is at or above the ${threshold}% preflight limit." >&2
    return 1
  fi
}

amw_capacity_runtime_ok() {
  local summary_path="${1:?AMW capacity summary path is required}"
  log_amw_capacity_summary "$summary_path"
  if ! jq -e '.capacity_samples_complete == true' \
      "$summary_path" >/dev/null; then
    return 1
  fi
  if jq -e '.capacity_ok == true' "$summary_path" >/dev/null; then
    return 0
  fi
  return 2
}

write_amw_capacity_markdown() {
  local summary_path="${1:?AMW capacity summary path is required}"
  local output_path="${2:?AMW capacity markdown output path is required}"
  local status

  status=$(jq -r \
    'if .capacity_samples_complete != true
     then "unverifiable"
     elif .capacity_ok
     then "complete"
     else "throttled"
     end' \
    "$summary_path")
  {
    echo "# Azure Monitor workspace capacity audit"
    echo
    echo "- Status: **$status**"
    echo "- Window: \`$(jq -r '.window.start' "$summary_path")\` to \`$(jq -r '.window.end' "$summary_path")\`"
    echo "- Active series: $(jq -r '.active_series.maximum' "$summary_path") / $(jq -r '.active_series.limit' "$summary_path") ($(jq -r '.active_series.maximum_percent' "$summary_path")%)"
    echo "- Events per minute received: $(jq -r '.events_per_minute.maximum_received' "$summary_path") / $(jq -r '.events_per_minute.limit' "$summary_path") ($(jq -r '.events_per_minute.maximum_percent' "$summary_path")%)"
    echo "- Limit-throttled events: $(jq -r '.limit_throttling.events_dropped' "$summary_path")"
    echo "- Limit-throttled time-series samples: $(jq -r '.limit_throttling.time_series_samples_dropped' "$summary_path")"
    echo
    echo "## Drops by reason"
    echo
    echo "| Metric | Reason | Total |"
    echo "|---|---|---:|"
    jq -r \
      '.drops_by_reason[]
        | "| \(.metric) | \(.reason) | \(.total) |"' \
      "$summary_path"
  } > "$output_path"
}

ensure_azure_provider_registered() {
  local namespace="${1:?Azure resource provider namespace is required}"
  local force_registration="${2:-false}"
  local timeout="${AKS_PROVIDER_REGISTRATION_TIMEOUT_SECONDS:-1800}"
  local poll_seconds="${AKS_PROVIDER_REGISTRATION_POLL_SECONDS:-15}"
  local deadline=$(( $(date +%s) + timeout ))
  local registration_requested=false
  local state=""
  local error_file

  while [ "$(date +%s)" -lt "$deadline" ]; do
    error_file=$(mktemp)
    if state=$(az provider show \
        --namespace "$namespace" \
        --query registrationState \
        -o tsv 2>"$error_file"); then
      rm -f "$error_file"
      if [ "$state" = "Registered" ] && {
        [ "${force_registration,,}" != "true" ] ||
          [ "$registration_requested" = "true" ]
      }; then
        echo "Resource provider $namespace is registered."
        return 0
      fi
    else
      echo "##vso[task.logissue type=warning;] Unable to query resource provider $namespace: $(tr '\n' ' ' < "$error_file")"
      rm -f "$error_file"
      state=""
    fi

    if [ "${force_registration,,}" = "true" ] &&
       [ "$registration_requested" != "true" ]; then
      echo "Forcing resource provider re-registration for $namespace..."
      if az provider register \
          --namespace "$namespace" \
          --output none; then
        registration_requested=true
      else
        echo "##vso[task.logissue type=warning;] Forced resource provider registration request for $namespace failed; retrying."
      fi
    elif [ "$state" != "Registering" ]; then
      echo "Requesting resource provider registration for $namespace..."
      if ! az provider register \
          --namespace "$namespace" \
          --output none; then
        echo "##vso[task.logissue type=warning;] Resource provider registration request for $namespace failed; polling and retrying."
      fi
    else
      echo "Resource provider $namespace is Registering."
    fi
    sleep "$poll_seconds"
  done

  echo "Timed out waiting for resource provider $namespace registration." >&2
  return 1
}

snapshot_label_value() {
  printf '%s' "$1" \
    | sed -E 's/[^a-zA-Z0-9_.:-]+/_/g; s/^_+//; s/_+$//'
}

initialize_managed_telemetry() {
  : "${MANIFEST_PATH:?MANIFEST_PATH is required}"
  : "${OUTPUT_DIR:?OUTPUT_DIR is required}"
  : "${RUN_ID:?RUN_ID is required}"

  if [ ! -s "$MANIFEST_PATH" ]; then
    echo "Managed Prometheus run manifest not found at $MANIFEST_PATH" >&2
    return 1
  fi

  mkdir -p "$OUTPUT_DIR"
  collection_manifest="$OUTPUT_DIR/run-manifest.json"
  configured_at=$(jq -r '.configured_at' "$MANIFEST_PATH")
  amw_id=$(jq -r '.workspace.id' "$MANIFEST_PATH")
  capacity_window_start=$(jq -r \
    '.workspace.capacity_guard.monitoring_window_start // .configured_at' \
    "$MANIFEST_PATH")
  endpoint=$(jq -r '.query.resource_endpoint' "$MANIFEST_PATH")
  resource_scope=$(jq -r '.query.resource_scope' "$MANIFEST_PATH")
  law_customer_id=$(jq -r '.logs.workspace.customer_id' "$MANIFEST_PATH")
  resource_ids_json=$(jq -c '[.clusters[].id]' "$MANIFEST_PATH")
}

load_collection_window() {
  if [ ! -s "$collection_manifest" ]; then
    echo "Managed telemetry collection window not found at $collection_manifest" >&2
    return 1
  fi

  end_time=$(jq -r '.collected_at' "$collection_manifest")
  audit_start=$(jq -r '.audit_window.start' "$collection_manifest")
  log_end_time=$(jq -r '.logs_window.end // .collected_at' "$collection_manifest")
  managed_prometheus_ready=$(jq -r \
    '.managed_prometheus_ready // false' \
    "$collection_manifest")
}

build_log_summary_query() {
  local query_end="${log_end_time:-$end_time}"
  log_summary_query=$(cat <<EOF
let ResourceIds=dynamic(${resource_ids_json});
union withsource=TableName isfuzzy=true
  AKSControlPlane,
  AKSAudit,
  AKSAuditAdmin
| where TimeGenerated between (datetime(${configured_at}) .. datetime(${query_end}))
| where _ResourceId in~ (ResourceIds)
| summarize Count=count(), First=min(TimeGenerated), Last=max(TimeGenerated)
  by TableName, Category=tostring(column_ifexists("Category", ""))
| order by TableName asc, Category asc
EOF
)
}
