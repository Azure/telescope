#!/usr/bin/env bash
set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=managed-prometheus-common.sh
source "$script_dir/managed-prometheus-common.sh"

if ! managed_telemetry_enabled; then
  echo "AKS control-plane managed Prometheus is disabled; skipping upload."
  exit 0
fi

: "${OUTPUT_DIR:?OUTPUT_DIR is required}"
: "${RUN_ID:?RUN_ID is required}"
mkdir -p "$OUTPUT_DIR"

storage_account="${CL2_PROM_SNAPSHOT_STORAGE_ACCOUNT:-cmshscaleprom}"
container="${CL2_PROM_SNAPSHOT_CONTAINER:-snapshots}"
build_branch="${BUILD_BRANCH:-unknown-branch}"
uploaded=0
while IFS= read -r -d '' file; do
  relative_path=${file#"$OUTPUT_DIR/"}
  blob_name="${build_branch}/managed-control-plane/${RUN_ID}/${relative_path}"
  echo "Uploading $file -> $storage_account/$container/$blob_name"
  az storage blob upload \
    --account-name "$storage_account" \
    --container-name "$container" \
    --name "$blob_name" \
    --file "$file" \
    --auth-mode login \
    --overwrite \
    --output none
  uploaded=$((uploaded + 1))
done < <(find "$OUTPUT_DIR" -type f -print0)

echo "Uploaded $uploaded managed telemetry artifact(s)."
