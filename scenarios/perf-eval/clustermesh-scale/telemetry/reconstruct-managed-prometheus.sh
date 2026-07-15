#!/usr/bin/env bash
set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=managed-prometheus-common.sh
source "$script_dir/managed-prometheus-common.sh"

if ! managed_telemetry_enabled; then
  echo "AKS control-plane managed Prometheus is disabled; skipping TSDB reconstruction."
  exit 0
fi

: "${TSDB_EXPORT_SCRIPT:?TSDB_EXPORT_SCRIPT is required}"

initialize_managed_telemetry
load_collection_window

prometheus_version="${AMW_PROMETHEUS_VERSION:-3.13.0}"
promtool_dir="$OUTPUT_DIR/promtool-${prometheus_version}"
promtool="$promtool_dir/promtool"
archive=""
cleanup() {
  unset PROMETHEUS_BEARER_TOKEN 2>/dev/null || true
  rm -rf "$promtool_dir"
  if [ -n "$archive" ]; then
    rm -f "$archive"
  fi
}
trap cleanup EXIT

if [ ! -x "$promtool" ]; then
  mkdir -p "$promtool_dir"
  archive="$OUTPUT_DIR/prometheus-${prometheus_version}.tar.gz"
  curl -fsSL \
    "https://github.com/prometheus/prometheus/releases/download/v${prometheus_version}/prometheus-${prometheus_version}.linux-amd64.tar.gz" \
    -o "$archive"
  tar xzf "$archive" \
    --strip-components=1 \
    -C "$promtool_dir" \
    "prometheus-${prometheus_version}.linux-amd64/promtool"
  rm -f "$archive"
  archive=""
fi

extra_openmetrics_args=()
while IFS= read -r cluster; do
  role=$(echo "$cluster" | jq -r '.role')
  platform_metrics="$OUTPUT_DIR/aks-platform-${role}.openmetrics"
  if [ -s "$platform_metrics" ]; then
    extra_openmetrics_args+=(--extra-openmetrics "$platform_metrics")
  else
    echo "##vso[task.logissue type=warning;] Platform OpenMetrics missing for $role; reconstructing AMW TSDB without that extra file."
  fi
done < <(jq -c '.clusters[]' "$MANIFEST_PATH")

token=$(az account get-access-token \
  --resource https://prometheus.monitor.azure.com \
  --query accessToken -o tsv)
export PROMETHEUS_BEARER_TOKEN="$token"

python3 "$TSDB_EXPORT_SCRIPT" \
  --endpoint "$endpoint" \
  --resource-scope "$resource_scope" \
  --start "$configured_at" \
  --end "$end_time" \
  --step-seconds "${AKS_MANAGED_TSDB_STEP_SECONDS:-15}" \
  --chunk-seconds "${AKS_MANAGED_TSDB_CHUNK_SECONDS:-600}" \
  --workers "${AKS_MANAGED_TSDB_WORKERS:-4}" \
  --metrics-per-block "${AKS_MANAGED_TSDB_METRICS_PER_BLOCK:-25}" \
  --promtool "$promtool" \
  "${extra_openmetrics_args[@]}" \
  --output-dir "$OUTPUT_DIR"

unset PROMETHEUS_BEARER_TOKEN

if [ -f "$OUTPUT_DIR/data/amw-export-manifest.json" ]; then
  cp "$OUTPUT_DIR/data/amw-export-manifest.json" \
    "$OUTPUT_DIR/amw-export-manifest.json"
  rm -rf "$OUTPUT_DIR/data"
fi

echo "Reconstructed managed Prometheus TSDB written to $OUTPUT_DIR"
