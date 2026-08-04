#!/usr/bin/env bash

set -euo pipefail

target_run_id="${CLUSTERMESH_DEBUG_TARGET_RUN_ID:?CLUSTERMESH_DEBUG_TARGET_RUN_ID is required}"
confirm="${CLUSTERMESH_DEBUG_CONFIRM_DELETE:?CLUSTERMESH_DEBUG_CONFIRM_DELETE is required}"
expected_subscription="${CLUSTERMESH_DEBUG_EXPECTED_SUBSCRIPTION_ID:?CLUSTERMESH_DEBUG_EXPECTED_SUBSCRIPTION_ID is required}"
expected_region="${CLUSTERMESH_DEBUG_EXPECTED_REGION:-eastus2}"

if [ "$confirm" != "$target_run_id" ]; then
  echo "Delete confirmation mismatch: CLUSTERMESH_DEBUG_CONFIRM_DELETE must equal $target_run_id." >&2
  exit 1
fi
if ! [[ "$target_run_id" =~ ^[0-9]+-[0-9a-f]{8}$ ]]; then
  echo "Invalid preserved RUN_ID '$target_run_id'; expected <build-id>-<8 hex>." >&2
  exit 1
fi
actual_subscription=$(az account show --query id -o tsv)
if [[ "${actual_subscription,,}" != "${expected_subscription,,}" ]]; then
  echo "Expected subscription $expected_subscription, got $actual_subscription." >&2
  exit 1
fi

rg_json=$(az group show --name "$target_run_id" -o json)
if [[ "$(jq -r '.location // empty' <<< "$rg_json" | tr '[:upper:]' '[:lower:]')" != "${expected_region,,}" ]]; then
  echo "Refusing to delete RG outside expected region $expected_region." >&2
  exit 1
fi
if [ "$(jq -r '.tags.clustermesh_debug_preserved // "false"' <<< "$rg_json")" != "true" ]; then
  echo "Refusing to delete RG without clustermesh_debug_preserved=true." >&2
  exit 1
fi
if [ "$(jq -r '.tags.scenario // empty' <<< "$rg_json")" != "perf-eval-clustermesh-scale" ]; then
  echo "Refusing to delete RG with unexpected scenario tag." >&2
  exit 1
fi

az group delete --name "$target_run_id" --yes --no-wait --only-show-errors
deadline=$(( $(date +%s) + 7200 ))
while [ "$(date +%s)" -lt "$deadline" ]; do
  if ! az group show --name "$target_run_id" --only-show-errors >/dev/null 2>&1; then
    echo "Deleted preserved debug RG $target_run_id."
    exit 0
  fi
  sleep 30
done
echo "Preserved debug RG $target_run_id still exists after 7200s." >&2
exit 1
