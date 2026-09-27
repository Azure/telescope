#!/usr/bin/env bash

set -euo pipefail

target_run_id="${CLUSTERMESH_DEBUG_TARGET_RUN_ID:?CLUSTERMESH_DEBUG_TARGET_RUN_ID is required}"
expected_subscription="${CLUSTERMESH_DEBUG_EXPECTED_SUBSCRIPTION_ID:?CLUSTERMESH_DEBUG_EXPECTED_SUBSCRIPTION_ID is required}"
expected_region="${CLUSTERMESH_DEBUG_EXPECTED_REGION:-eastus2}"
expected_count="${CLUSTERMESH_DEBUG_EXPECTED_CLUSTER_COUNT:-100}"
expected_tfvars_sha="${CLUSTERMESH_DEBUG_EXPECTED_TFVARS_SHA256:?CLUSTERMESH_DEBUG_EXPECTED_TFVARS_SHA256 is required}"
extend_lease_hours="${CLUSTERMESH_DEBUG_EXTEND_LEASE_HOURS:-0}"
manifest_path="${CLUSTERMESH_DEBUG_MANIFEST_PATH:-$(pwd)/scale-reuse-validation.json}"
require_overlay_reset="${CLUSTERMESH_DEBUG_REQUIRE_OVERLAY_RESET:-false}"
allow_failed_running_clusters="${CLUSTERMESH_DEBUG_ALLOW_FAILED_RUNNING_CLUSTERS:-false}"
validation_tmp_dir=$(mktemp -d)
node_resource_groups_file="$validation_tmp_dir/node-resource-groups.json"
subscription_groups_file="$validation_tmp_dir/subscription-groups.json"
node_resource_group_manifest_file="$validation_tmp_dir/node-resource-group-manifest.json"

cleanup_validation_tmp_dir() {
  rm -f \
    "$node_resource_groups_file" \
    "$subscription_groups_file" \
    "$node_resource_group_manifest_file"
  rmdir "$validation_tmp_dir" 2>/dev/null || true
}
trap cleanup_validation_tmp_dir EXIT

if ! [[ "$target_run_id" =~ ^[0-9]+-[0-9a-f]{8}$ ]]; then
  echo "Invalid preserved RUN_ID '$target_run_id'; expected <build-id>-<8 hex>." >&2
  exit 1
fi
if ! [[ "$expected_count" =~ ^[1-9][0-9]*$ ]]; then
  echo "CLUSTERMESH_DEBUG_EXPECTED_CLUSTER_COUNT must be a positive integer." >&2
  exit 1
fi
if ! [[ "$extend_lease_hours" =~ ^[0-9]+$ ]]; then
  echo "CLUSTERMESH_DEBUG_EXTEND_LEASE_HOURS must be a non-negative integer." >&2
  exit 1
fi
if [[ "$allow_failed_running_clusters" != "true" &&
      "$allow_failed_running_clusters" != "false" ]]; then
  echo "CLUSTERMESH_DEBUG_ALLOW_FAILED_RUNNING_CLUSTERS must be true or false." >&2
  exit 1
fi

actual_subscription=$(az account show --query id -o tsv)
if [[ "${actual_subscription,,}" != "${expected_subscription,,}" ]]; then
  echo "Expected subscription $expected_subscription, got $actual_subscription." >&2
  exit 1
fi

rg_json=$(az group show --name "$target_run_id" -o json)
location=$(jq -r '.location // empty' <<< "$rg_json")
preserved=$(jq -r '.tags.clustermesh_debug_preserved // "false"' <<< "$rg_json")
tagged_run_id=$(jq -r '.tags.run_id // empty' <<< "$rg_json")
scenario=$(jq -r '.tags.scenario // empty' <<< "$rg_json")
tagged_expected_count=$(jq -r '.tags.clustermesh_debug_expected_clusters // empty' <<< "$rg_json")
tagged_tfvars_sha=$(jq -r '.tags.clustermesh_debug_tfvars_sha256 // empty' <<< "$rg_json")

if [[ "${location,,}" != "${expected_region,,}" ]]; then
  echo "Preserved RG region mismatch: expected $expected_region, got $location." >&2
  exit 1
fi
if [ "$preserved" != "true" ]; then
  echo "RG $target_run_id is not tagged clustermesh_debug_preserved=true." >&2
  exit 1
fi
if [ "$tagged_run_id" != "$target_run_id" ]; then
  echo "RG run_id tag mismatch: expected $target_run_id, got ${tagged_run_id:-missing}." >&2
  exit 1
fi
if [ "$scenario" != "perf-eval-clustermesh-scale" ]; then
  echo "RG scenario tag mismatch: expected perf-eval-clustermesh-scale, got ${scenario:-missing}." >&2
  exit 1
fi
if [ "$tagged_expected_count" != "$expected_count" ]; then
  echo "RG expected-cluster tag mismatch: expected $expected_count, got ${tagged_expected_count:-missing}." >&2
  exit 1
fi
if [ "$tagged_tfvars_sha" != "$expected_tfvars_sha" ]; then
  echo "RG tfvars SHA mismatch: expected $expected_tfvars_sha, got ${tagged_tfvars_sha:-missing}." >&2
  exit 1
fi

clusters=$(az resource list \
  --resource-group "$target_run_id" \
  --resource-type Microsoft.ContainerService/managedClusters \
  --query "[?tags.run_id=='${target_run_id}' && starts_with(tags.role, 'mesh-')].{name:name,rg:resourceGroup,role:tags.role,location:location}" \
  -o json)

cluster_count=$(jq 'length' <<< "$clusters")
if [ "$cluster_count" -ne "$expected_count" ]; then
  echo "Expected $expected_count preserved mesh clusters, found $cluster_count." >&2
  exit 1
fi

if ! jq -e --argjson expected "$expected_count" '
    ([.[].role | capture("^mesh-(?<n>[0-9]+)$").n | tonumber] | sort)
      == [range(1; $expected + 1)]
  ' <<< "$clusters" >/dev/null; then
  echo "Preserved cluster role inventory is not exactly mesh-1..mesh-$expected_count." >&2
  exit 1
fi
if ! jq -e --arg region "$expected_region" '
    all(.[]; ((.location // "") | ascii_downcase) == ($region | ascii_downcase))
  ' <<< "$clusters" >/dev/null; then
  echo "One or more preserved mesh clusters are outside $expected_region." >&2
  exit 1
fi

aks=$(az aks list --resource-group "$target_run_id" -o json)
if [ "$(jq 'length' <<< "$aks")" -ne "$expected_count" ]; then
  echo "Expected exactly $expected_count total AKS clusters in the preserved RG." >&2
  exit 1
fi
unhealthy=$(jq -c --arg allow_failed_running "$allow_failed_running_clusters" '
  [.[] | select(
    ((.powerState.code // "Running") != "Running") or
    (
      .provisioningState != "Succeeded" and
      (($allow_failed_running == "true" and .provisioningState == "Failed") | not)
    )
  ) | {name, provisioningState, powerState}]
' <<< "$aks")
if [ "$(jq 'length' <<< "$unhealthy")" -ne 0 ]; then
  echo "Preserved AKS inventory contains unhealthy clusters: $unhealthy" >&2
  exit 1
fi
tolerated_failed=$(jq -c '
  [.[] | select(
    .provisioningState == "Failed" and
    ((.powerState.code // "Running") == "Running")
  ) | {name, provisioningState, powerState}]
' <<< "$aks")
if [ "$(jq 'length' <<< "$tolerated_failed")" -ne 0 ]; then
  echo "Allowing Failed/Running AKS records for downstream worker and Fleet validation: $tolerated_failed"
fi

node_resource_groups=$(jq -c '
  [.[] | {
    name: (.nodeResourceGroup // ""),
    cluster_name: (.name // ""),
    cluster_id: (.id // ""),
    role: (.tags.role // ""),
    location: (.location // "")
  }]
' <<< "$aks")
if ! jq -e --argjson expected "$expected_count" '
    length == $expected and
    all(.[];
      ((.name | type) == "string" and (.name | length) > 0) and
      ((.cluster_name | type) == "string" and (.cluster_name | length) > 0) and
      ((.cluster_id | type) == "string" and (.cluster_id | length) > 0) and
      ((.role | type) == "string" and (.role | test("^mesh-[0-9]+$")))
    )
  ' <<< "$node_resource_groups" >/dev/null; then
  echo "Preserved AKS inventory has invalid nodeResourceGroup metadata." >&2
  exit 1
fi
if ! jq -e '
    ([.[].name | ascii_downcase] | length) ==
    ([.[].name | ascii_downcase] | unique | length)
  ' <<< "$node_resource_groups" >/dev/null; then
  echo "Preserved AKS inventory has duplicate nodeResourceGroup names." >&2
  exit 1
fi

printf '%s\n' "$node_resource_groups" > "$node_resource_groups_file"
az group list \
  --query '[].{name:name,location:location,managedBy:managedBy,deletion_due_time:tags.deletion_due_time}' \
  -o json \
  --only-show-errors > "$subscription_groups_file"
node_resource_group_inventory=$(jq -cn \
  --slurpfile expected "$node_resource_groups_file" \
  --slurpfile actual "$subscription_groups_file" '
    ($actual[0] | INDEX(.name | ascii_downcase)) as $by_name
    | [$expected[0][] as $item
      | ($by_name[($item.name | ascii_downcase)] // null) as $group
      | $item + {
          exists: ($group != null),
          actual_location: ($group.location // ""),
          managed_by: ($group.managedBy // ""),
          deletion_due_time: ($group.deletion_due_time // "")
        }]
  ')
missing_node_resource_groups=$(jq -c '
  [.[] | select(.exists | not) | {
    role,
    cluster_name,
    node_resource_group: .name
  }]
' <<< "$node_resource_group_inventory")
missing_node_resource_group_count=$(jq 'length' <<< "$missing_node_resource_groups")
if [ "$missing_node_resource_group_count" -ne 0 ]; then
  missing_node_resource_group_sample=$(jq -c '.[0:20]' <<< "$missing_node_resource_groups")
  echo "Preserved AKS node resource groups are missing: count=$missing_node_resource_group_count sample=$missing_node_resource_group_sample. These clusters cannot be repaired in place; rebuild the preserved environment." >&2
  exit 1
fi

invalid_node_resource_groups=$(jq -c --arg region "$expected_region" '
  [.[] | select(
    ((.actual_location | ascii_downcase) != ($region | ascii_downcase)) or
    ((.managed_by | ascii_downcase) != (.cluster_id | ascii_downcase))
  ) | {
    role,
    cluster_name,
    node_resource_group: .name,
    expected_cluster_id: .cluster_id,
    managed_by,
    expected_location: $region,
    actual_location
  }]
' <<< "$node_resource_group_inventory")
invalid_node_resource_group_count=$(jq 'length' <<< "$invalid_node_resource_groups")
if [ "$invalid_node_resource_group_count" -ne 0 ]; then
  invalid_node_resource_group_sample=$(jq -c '.[0:20]' <<< "$invalid_node_resource_groups")
  echo "Preserved AKS node resource groups do not match their clusters: count=$invalid_node_resource_group_count sample=$invalid_node_resource_group_sample" >&2
  exit 1
fi
node_resource_group_count=$(jq 'length' <<< "$node_resource_group_inventory")

fleet_count=$(az resource list \
  --resource-group "$target_run_id" \
  --resource-type Microsoft.ContainerService/fleets \
  --query 'length(@)' -o tsv)
if [ "${require_overlay_reset,,}" = "true" ] && [ "$fleet_count" -ne 0 ]; then
  echo "Resume requires the Fleet overlay to be reset first; found $fleet_count Fleet resource(s)." >&2
  exit 1
fi

existing_deletion_due_time=$(jq -r '.tags.deletion_due_time // empty' <<< "$rg_json")
node_resource_groups_extended=0
if [ "$extend_lease_hours" -gt 0 ]; then
  requested_deletion_due_time=$(date -u -d "+${extend_lease_hours} hours" +%Y-%m-%dT%H:%M:%SZ)
  requested_deletion_due_epoch=$(date -u -d "$requested_deletion_due_time" +%s)
  existing_deletion_due_epoch=""
  if [ -n "$existing_deletion_due_time" ]; then
    existing_deletion_due_epoch=$(date -u -d "$existing_deletion_due_time" +%s 2>/dev/null || true)
  fi
  if [[ "$existing_deletion_due_epoch" =~ ^[0-9]+$ ]] &&
    [ "$existing_deletion_due_epoch" -gt "$requested_deletion_due_epoch" ]; then
    deletion_due_time="$existing_deletion_due_time"
    echo "Preserving later existing lease $deletion_due_time instead of shortening it to $requested_deletion_due_time."
  else
    deletion_due_time="$requested_deletion_due_time"
  fi
  deletion_due_epoch=$(date -u -d "$deletion_due_time" +%s)

  while IFS= read -r node_rg_row; do
    node_rg=$(jq -r '.name' <<< "$node_rg_row")
    existing_node_deletion_due_time=$(jq -r '.deletion_due_time // empty' <<< "$node_rg_row")
    existing_node_deletion_due_epoch=""
    if [ -n "$existing_node_deletion_due_time" ]; then
      existing_node_deletion_due_epoch=$(date -u -d "$existing_node_deletion_due_time" +%s 2>/dev/null || true)
    fi
    if [[ "$existing_node_deletion_due_epoch" =~ ^[0-9]+$ ]] &&
      [ "$existing_node_deletion_due_epoch" -ge "$deletion_due_epoch" ]; then
      echo "Preserving later existing node RG lease $existing_node_deletion_due_time on $node_rg."
      continue
    fi
    az group update --name "$node_rg" \
      --set tags.deletion_due_time="$deletion_due_time" \
            tags.clustermesh_debug_last_validation_build="${BUILD_BUILDID:-manual}" \
      --only-show-errors >/dev/null
    node_resource_groups_extended=$((node_resource_groups_extended + 1))
  done < <(jq -c '.[]' <<< "$node_resource_group_inventory")

  az group update --name "$target_run_id" \
    --set tags.deletion_due_time="$deletion_due_time" \
          tags.clustermesh_debug_last_validation_build="${BUILD_BUILDID:-manual}" \
    --only-show-errors >/dev/null
else
  deletion_due_time="$existing_deletion_due_time"
fi

node_resource_group_manifest=$(jq -c \
  --arg required_deletion_due_time "$deletion_due_time" '
    map(. + {required_deletion_due_time: $required_deletion_due_time})
  ' <<< "$node_resource_group_inventory")
printf '%s\n' "$node_resource_group_manifest" > "$node_resource_group_manifest_file"

mkdir -p "$(dirname "$manifest_path")"
jq -n \
  --arg target_run_id "$target_run_id" \
  --arg subscription_id "$actual_subscription" \
  --arg region "$location" \
  --arg deletion_due_time "$deletion_due_time" \
  --argjson cluster_count "$cluster_count" \
  --argjson fleet_count "$fleet_count" \
  --argjson clusters "$clusters" \
  --argjson node_resource_group_count "$node_resource_group_count" \
  --argjson node_resource_groups_extended "$node_resource_groups_extended" \
  --slurpfile node_resource_groups "$node_resource_group_manifest_file" \
  '{
    target_run_id: $target_run_id,
    subscription_id: $subscription_id,
    region: $region,
    deletion_due_time: $deletion_due_time,
    cluster_count: $cluster_count,
    fleet_count: $fleet_count,
    clusters: $clusters,
    node_resource_group_count: $node_resource_group_count,
    node_resource_groups_extended: $node_resource_groups_extended,
    node_resource_groups: $node_resource_groups[0]
  }' > "$manifest_path"

echo "Validated preserved scale RG $target_run_id: expected=$expected_count clusters=$cluster_count node_rgs=$node_resource_group_count node_rgs_extended=$node_resource_groups_extended fleet=$fleet_count lease=$deletion_due_time"
