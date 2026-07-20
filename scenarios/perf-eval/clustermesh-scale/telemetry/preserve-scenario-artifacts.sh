#!/usr/bin/env bash
set -uo pipefail

shopt -s nullglob

: "${SCENARIO_REPORT_DIR:?SCENARIO_REPORT_DIR is required}"
: "${SCENARIO_NAME:?SCENARIO_NAME is required}"
: "${RUN_ID:?RUN_ID is required}"
: "${BUILD_ID:?BUILD_ID is required}"
: "${SNAPSHOT_TIER:?SNAPSHOT_TIER is required}"
: "${BUILD_BRANCH:?BUILD_BRANCH is required}"
: "${STORAGE_ACCOUNT_NAME:?STORAGE_ACCOUNT_NAME is required}"
: "${CONTAINER_NAME:?CONTAINER_NAME is required}"
: "${TARGET_SUBSCRIPTION_ID:?TARGET_SUBSCRIPTION_ID is required}"
: "${WORKER_SUMMARY_FILE:?WORKER_SUMMARY_FILE is required}"
: "${RELABEL_SCRIPT:?RELABEL_SCRIPT is required}"

snapshot_enabled="${CL2_PROM_SNAPSHOT_ENABLED:-false}"
snapshot_target="${CL2_PROM_SNAPSHOT_TARGET:-artifact}"
summary_file="$SCENARIO_REPORT_DIR/artifact-preservation-summary.json"
summary_tmp="${summary_file}.partial"

expected_roles=()
uploaded_snapshot_roles=()
missing_snapshot_roles=()
errors=()
expected_successful_worker_count=0
uploaded_snapshot_count=0
uploaded_snapshot_bytes=0
uploaded_audit_count=0
uploaded_audit_bytes=0
uploaded_acns_count=0
uploaded_acns_bytes=0
uploaded_lifecycle_count=0
uploaded_lifecycle_bytes=0
worker_summary_valid=false
operation_failed=false
no_op_reason=""

mkdir -p "$SCENARIO_REPORT_DIR"
rm -f -- "$summary_tmp"
trap 'rm -f -- "$summary_tmp"' EXIT

array_json() {
  if [ "$#" -eq 0 ]; then
    printf '[]'
    return
  fi
  printf '%s\n' "$@" | jq -R . | jq -s .
}

contains_value() {
  local needle="$1"
  shift
  local value
  for value in "$@"; do
    if [ "$value" = "$needle" ]; then
      return 0
    fi
  done
  return 1
}

add_error() {
  errors+=("$1")
  operation_failed=true
  echo "$1" >&2
}

load_worker_summary() {
  if [ ! -s "$WORKER_SUMMARY_FILE" ]; then
    return 1
  fi
  if ! jq -e '
      (.succeeded_count | type == "number") and
      (.succeeded_count >= 0) and
      (.succeeded_count == (.succeeded_count | floor)) and
      (.succeeded_roles | type == "array") and
      all(.succeeded_roles[];
        (type == "string") and
        (length > 0) and
        (contains("/") | not) and
        (. != ".") and
        (. != "..")) and
      (.succeeded_count == (.succeeded_roles | length)) and
      (.succeeded_count == ([.succeeded_roles[]] | unique | length))
    ' "$WORKER_SUMMARY_FILE" >/dev/null; then
    return 1
  fi
  mapfile -t expected_roles < <(
    jq -r '.succeeded_roles[]' "$WORKER_SUMMARY_FILE" | sort
  )
  expected_successful_worker_count="${#expected_roles[@]}"
  worker_summary_valid=true
}

write_summary() {
  local success="$1"
  local expected_roles_json uploaded_roles_json missing_roles_json errors_json
  local uploaded_total_bytes
  expected_roles_json=$(array_json "${expected_roles[@]}")
  uploaded_roles_json=$(array_json "${uploaded_snapshot_roles[@]}")
  missing_roles_json=$(array_json "${missing_snapshot_roles[@]}")
  errors_json=$(array_json "${errors[@]}")
  uploaded_total_bytes=$((uploaded_snapshot_bytes + uploaded_audit_bytes + uploaded_acns_bytes + uploaded_lifecycle_bytes))

  if ! jq -n \
      --arg scenario "$SCENARIO_NAME" \
      --arg report_dir "$SCENARIO_REPORT_DIR" \
      --arg run_id "$RUN_ID" \
      --arg build_id "$BUILD_ID" \
      --arg snapshot_tier "$SNAPSHOT_TIER" \
      --arg build_branch "$BUILD_BRANCH" \
      --arg storage_account "$STORAGE_ACCOUNT_NAME" \
      --arg container "$CONTAINER_NAME" \
      --arg snapshot_enabled "$snapshot_enabled" \
      --arg snapshot_target "$snapshot_target" \
      --arg no_op_reason "$no_op_reason" \
      --argjson worker_summary_valid "$worker_summary_valid" \
      --argjson expected_successful_worker_count \
        "$expected_successful_worker_count" \
      --argjson expected_successful_worker_roles "$expected_roles_json" \
      --argjson uploaded_snapshot_count "$uploaded_snapshot_count" \
      --argjson uploaded_snapshot_roles "$uploaded_roles_json" \
      --argjson missing_snapshot_roles "$missing_roles_json" \
      --argjson uploaded_snapshot_bytes "$uploaded_snapshot_bytes" \
      --argjson uploaded_audit_count "$uploaded_audit_count" \
      --argjson uploaded_audit_bytes "$uploaded_audit_bytes" \
      --argjson uploaded_acns_count "$uploaded_acns_count" \
      --argjson uploaded_acns_bytes "$uploaded_acns_bytes" \
      --argjson uploaded_lifecycle_count "$uploaded_lifecycle_count" \
      --argjson uploaded_lifecycle_bytes "$uploaded_lifecycle_bytes" \
      --argjson uploaded_total_bytes "$uploaded_total_bytes" \
      --argjson errors "$errors_json" \
      --argjson success "$success" \
      '{
        schema_version: 1,
        scenario: $scenario,
        scenario_report_dir: $report_dir,
        run_id: $run_id,
        build_id: $build_id,
        snapshot_tier: $snapshot_tier,
        build_branch: $build_branch,
        storage_account: $storage_account,
        container: $container,
        snapshot_enabled: ($snapshot_enabled | ascii_downcase == "true"),
        snapshot_target: $snapshot_target,
        no_op_reason: (if $no_op_reason == "" then null else $no_op_reason end),
        worker_summary_valid: $worker_summary_valid,
        expected_successful_worker_count: $expected_successful_worker_count,
        expected_successful_worker_roles: $expected_successful_worker_roles,
        uploaded_snapshot_count: $uploaded_snapshot_count,
        uploaded_snapshot_roles: $uploaded_snapshot_roles,
        missing_snapshot_roles: $missing_snapshot_roles,
        uploaded_snapshot_bytes: $uploaded_snapshot_bytes,
        uploaded_audit_count: $uploaded_audit_count,
        uploaded_audit_bytes: $uploaded_audit_bytes,
        uploaded_acns_count: $uploaded_acns_count,
        uploaded_acns_bytes: $uploaded_acns_bytes,
        uploaded_lifecycle_count: $uploaded_lifecycle_count,
        uploaded_lifecycle_bytes: $uploaded_lifecycle_bytes,
        uploaded_total_bytes: $uploaded_total_bytes,
        errors: $errors,
        success: $success
      }' > "$summary_tmp"; then
    echo "Failed to write preservation summary $summary_tmp" >&2
    return 1
  fi
  mv -f -- "$summary_tmp" "$summary_file"
}

upload_and_verify() {
  local file="$1"
  local blob_name="$2"
  local artifact_type="$3"
  local role="${4:-}"
  local delete_after_upload="${5:-false}"
  local size remote_size

  size=$(stat -c%s "$file" 2>/dev/null || printf '0')
  echo "Uploading $file (${size} bytes) -> ${STORAGE_ACCOUNT_NAME}/${CONTAINER_NAME}/${blob_name}"
  if ! az storage blob upload \
      --account-name "$STORAGE_ACCOUNT_NAME" \
      --container-name "$CONTAINER_NAME" \
      --name "$blob_name" \
      --file "$file" \
      --auth-mode login \
      --overwrite \
      --output none; then
    add_error "Upload failed for $file"
    return 1
  fi

  if ! remote_size=$(az storage blob show \
      --account-name "$STORAGE_ACCOUNT_NAME" \
      --container-name "$CONTAINER_NAME" \
      --name "$blob_name" \
      --auth-mode login \
      --query properties.contentLength \
      --output tsv); then
    add_error "Upload verification failed for $file"
    return 1
  fi
  remote_size=${remote_size//$'\r'/}
  if ! [[ "$remote_size" =~ ^[0-9]+$ ]] || [ "$remote_size" -ne "$size" ]; then
    add_error "Upload verification size mismatch for $file: local=$size remote=${remote_size:-unknown}"
    return 1
  fi

  case "$artifact_type" in
    snapshot)
      uploaded_snapshot_count=$((uploaded_snapshot_count + 1))
      uploaded_snapshot_bytes=$((uploaded_snapshot_bytes + size))
      if ! contains_value "$role" "${uploaded_snapshot_roles[@]}"; then
        uploaded_snapshot_roles+=("$role")
      fi
      ;;
    audit)
      uploaded_audit_count=$((uploaded_audit_count + 1))
      uploaded_audit_bytes=$((uploaded_audit_bytes + size))
      ;;
    acns)
      uploaded_acns_count=$((uploaded_acns_count + 1))
      uploaded_acns_bytes=$((uploaded_acns_bytes + size))
      ;;
    lifecycle)
      uploaded_lifecycle_count=$((uploaded_lifecycle_count + 1))
      uploaded_lifecycle_bytes=$((uploaded_lifecycle_bytes + size))
      ;;
  esac

  if [ "$delete_after_upload" = "true" ]; then
    if ! rm -f -- "$file"; then
      echo "Warning: unable to remove verified snapshot $file" >&2
    fi
  fi
}

load_worker_summary || true

if [ "${snapshot_enabled,,}" != "true" ]; then
  no_op_reason="snapshots-disabled"
  if ! write_summary true; then
    exit 1
  fi
  echo "Prometheus snapshots are disabled; scenario preservation is a no-op."
  exit 0
fi
if [ "${snapshot_target,,}" != "blob" ]; then
  no_op_reason="snapshot-target-${snapshot_target}"
  if ! write_summary true; then
    exit 1
  fi
  echo "Prometheus snapshot target is $snapshot_target; scenario preservation is a no-op."
  exit 0
fi

if [ "$worker_summary_valid" != "true" ]; then
  add_error "Worker summary is missing or invalid: $WORKER_SUMMARY_FILE"
fi
if [ ! -f "$RELABEL_SCRIPT" ]; then
  add_error "Relabel script does not exist: $RELABEL_SCRIPT"
fi
for command_name in az jq gzip tar stat find sort; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    add_error "Required command is unavailable: $command_name"
  fi
done

azure_ready=true
if ! az account set --subscription "$TARGET_SUBSCRIPTION_ID"; then
  add_error "Unable to select Azure subscription $TARGET_SUBSCRIPTION_ID"
  azure_ready=false
else
  actual_subscription_id=$(
    az account show --query id --output tsv 2>/dev/null || true
  )
  if [[ "${actual_subscription_id,,}" != "${TARGET_SUBSCRIPTION_ID,,}" ]]; then
    add_error "Expected Azure subscription $TARGET_SUBSCRIPTION_ID, got ${actual_subscription_id:-unknown}"
    azure_ready=false
  fi
fi

if [ "$azure_ready" = "true" ]; then
  while IFS= read -r -d '' lifecycle_file; do
    blob_name="${BUILD_BRANCH}/lifecycle/${SCENARIO_NAME}/${RUN_ID}/$(basename "$lifecycle_file")"
    upload_and_verify "$lifecycle_file" "$blob_name" lifecycle || true
  done < <(
    find "$SCENARIO_REPORT_DIR" \
      -type f \
      \( -name 'worker-summary.json' \
         -o -name 'scenario-policy.json' \
         -o -name 'NodeChurnTimings_*.json' \
         -o -name 'ApiserverFailureTimings_*.json' \
         -o -name 'IsolationChurnTimings_*.json' \) \
      -print0 | sort -z
  )

  while IFS= read -r -d '' audit; do
    role=$(basename "$(dirname "$(dirname "$audit")")")
    extension="${audit##*.}"
    blob_name="${BUILD_BRANCH}/telemetry-audit-self-hosted/${SCENARIO_NAME}/${RUN_ID}/telemetry-audit-self-hosted-${role}.${extension}"
    upload_and_verify "$audit" "$blob_name" audit || true
  done < <(
    find "$SCENARIO_REPORT_DIR" \
      -mindepth 3 \
      -maxdepth 3 \
      -type f \
      \( -name 'telemetry-audit-self-hosted.json' \
         -o -name 'telemetry-audit-self-hosted.md' \) \
      -print0 | sort -z
  )

  while IFS= read -r -d '' acns_file; do
    role=$(basename "$(dirname "$(dirname "$(dirname "$acns_file")")")")
    blob_name="${BUILD_BRANCH}/acns/${SCENARIO_NAME}/${RUN_ID}/${role}/$(basename "$acns_file")"
    upload_and_verify "$acns_file" "$blob_name" acns || true
  done < <(
    find "$SCENARIO_REPORT_DIR" \
      -mindepth 4 \
      -maxdepth 4 \
      -type f \
      -path '*/telemetry/acns/*' \
      -print0 | sort -z
  )
fi

snapshot_files=()
while IFS= read -r -d '' snapshot; do
  snapshot_files+=("$snapshot")
  if [ ! -s "$snapshot" ] ||
     ! gzip -t "$snapshot" 2>/dev/null ||
     ! tar -tzf "$snapshot" >/dev/null 2>&1; then
    add_error "Invalid Prometheus snapshot tarball: $snapshot"
  fi
done < <(
  find "$SCENARIO_REPORT_DIR" \
    -mindepth 2 \
    -maxdepth 2 \
    -type f \
    -name 'prom-snapshot-*.tar.gz' \
    -print0 | sort -z
)

relabel_ready=false
if [ "$azure_ready" = "true" ] &&
   [ -f "$RELABEL_SCRIPT" ] &&
   [ "${#snapshot_files[@]}" -gt 0 ]; then
  if CL2_REPORT_DIR="$SCENARIO_REPORT_DIR" \
      RUN_ID="$RUN_ID" \
      BUILD_ID="$BUILD_ID" \
      SNAPSHOT_TIER="$SNAPSHOT_TIER" \
      bash "$RELABEL_SCRIPT"; then
    relabel_ready=true
  else
    add_error "Prometheus snapshot relabeling failed for $SCENARIO_NAME"
  fi
elif [ "${#snapshot_files[@]}" -eq 0 ]; then
  relabel_ready=true
fi

if [ "$azure_ready" = "true" ] && [ "$relabel_ready" = "true" ]; then
  for snapshot in "${snapshot_files[@]}"; do
    role=$(basename "$(dirname "$snapshot")")
    if [ ! -s "$snapshot" ] ||
       ! gzip -t "$snapshot" 2>/dev/null ||
       ! tar -tzf "$snapshot" >/dev/null 2>&1; then
      add_error "Relabeled Prometheus snapshot is invalid: $snapshot"
      continue
    fi
    blob_name="${BUILD_BRANCH}/${SCENARIO_NAME}/${RUN_ID}/$(basename "$snapshot")"
    upload_and_verify "$snapshot" "$blob_name" snapshot "$role" true || true
  done
fi

if [ "${#uploaded_snapshot_roles[@]}" -gt 0 ]; then
  mapfile -t uploaded_snapshot_roles < <(
    printf '%s\n' "${uploaded_snapshot_roles[@]}" | sort -u
  )
fi
for role in "${expected_roles[@]}"; do
  if ! contains_value "$role" "${uploaded_snapshot_roles[@]}"; then
    missing_snapshot_roles+=("$role")
  fi
done
if [ "${#missing_snapshot_roles[@]}" -gt 0 ]; then
  operation_failed=true
  echo "Missing verified snapshot uploads for successful worker role(s): ${missing_snapshot_roles[*]}" >&2
fi

if [ "$operation_failed" = "true" ]; then
  write_summary false || true
  exit 1
fi

if ! write_summary true; then
  exit 1
fi
echo "Preserved $uploaded_snapshot_count snapshot(s), $uploaded_audit_count telemetry audit file(s), $uploaded_acns_count ACNS file(s), and $uploaded_lifecycle_count lifecycle file(s) for $SCENARIO_NAME."
