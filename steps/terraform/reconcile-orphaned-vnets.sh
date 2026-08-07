#!/usr/bin/env bash
set -euo pipefail

: "${ARM_SUBSCRIPTION_ID:?ARM_SUBSCRIPTION_ID is required}"
: "${RUN_ID:?RUN_ID is required}"
: "${REGION:?REGION is required}"
: "${TERRAFORM_INPUT_FILE:?TERRAFORM_INPUT_FILE is required}"
: "${TERRAFORM_INPUT_VARIABLES:?TERRAFORM_INPUT_VARIABLES is required}"

wait_timeout="${VNET_RECONCILE_WAIT_SECONDS:-900}"
poll_seconds="${VNET_RECONCILE_POLL_SECONDS:-20}"
reconcile_concurrency="${VNET_RECONCILE_CONCURRENCY:-10}"

for value in "$wait_timeout" "$poll_seconds" "$reconcile_concurrency"; do
  if ! [[ "$value" =~ ^[1-9][0-9]*$ ]]; then
    echo "VNet reconciliation settings must be positive integers." >&2
    exit 1
  fi
done

state_rc=0
state_list=$(terraform state list 2>&1) || state_rc=$?
if [ "$state_rc" -ne 0 ]; then
  if echo "$state_list" | grep -qi "No state file was found"; then
    state_list=""
  else
    echo "Failed to read Terraform state before VNet reconciliation: $state_list" >&2
    exit "$state_rc"
  fi
fi

list_rc=0
vnet_rows_output=$(az network vnet list \
  --subscription "$ARM_SUBSCRIPTION_ID" \
  --resource-group "$RUN_ID" \
  --query "[?location=='$REGION' && tags.run_id=='$RUN_ID'].[name,tags.role,id,provisioningState]" \
  --output tsv \
  --only-show-errors) || list_rc=$?
if [ "$list_rc" -ne 0 ]; then
  echo "Failed to enumerate VNets in $RUN_ID." >&2
  exit "$list_rc"
fi

if [ -z "$vnet_rows_output" ]; then
  echo "No existing run-owned VNets require pre-apply reconciliation."
  exit 0
fi

wait_for_vnet() {
  local vnet="${1:?VNet name is required}"
  local deadline state_out state_rc state

  deadline=$(($(date +%s) + wait_timeout))
  while [ "$(date +%s)" -lt "$deadline" ]; do
    state_rc=0
    state_out=$(az network vnet show \
      --subscription "$ARM_SUBSCRIPTION_ID" \
      --resource-group "$RUN_ID" \
      --name "$vnet" \
      --query provisioningState \
      --output tsv \
      --only-show-errors 2>&1) || state_rc=$?
    if [ "$state_rc" -ne 0 ]; then
      if echo "$state_out" |
        grep -qiE "NotFound|ResourceNotFound|ResourceGroupNotFound|could not be found"; then
        echo "[$vnet] disappeared before reconciliation."
        return 2
      fi
      echo "[$vnet] state query failed transiently: $state_out"
      sleep "$poll_seconds"
      continue
    fi
    state=$(printf '%s\n' "$state_out" | awk \
      '/^[[:space:]]*(Succeeded|Failed|Updating|Creating|Deleting)[[:space:]]*$/ { value=$1 } END { print value }')
    case "$state" in
      Succeeded)
        echo "[$vnet] provisioningState=Succeeded."
        return 0
        ;;
      Failed)
        echo "[$vnet] provisioningState=Failed."
        return 1
        ;;
      *)
        echo "[$vnet] provisioningState=${state:-unknown}; waiting."
        ;;
    esac
    sleep "$poll_seconds"
  done
  echo "[$vnet] did not reach a terminal state within ${wait_timeout}s." >&2
  return 1
}

recover_failed_vnet() {
  local vnet="${1:?VNet name is required}"
  local attempt update_out update_rc

  for attempt in $(seq 1 10); do
    update_rc=0
    update_out=$(timeout 180s az network vnet update \
      --subscription "$ARM_SUBSCRIPTION_ID" \
      --resource-group "$RUN_ID" \
      --name "$vnet" \
      --set "tags.telescope_recovery=$RUN_ID" \
      --output none \
      --only-show-errors 2>&1) || update_rc=$?
    if [ "$update_rc" -eq 0 ]; then
      echo "[$vnet] recovery PUT accepted on attempt $attempt/10."
      if wait_for_vnet "$vnet"; then
        return 0
      fi
    elif [ "$update_rc" -eq 124 ] || [ "$update_rc" -eq 137 ] ||
      echo "$update_out" |
      grep -qiE "InternalServerError|RetryableError|ServerTimeout|ServiceUnavailable|AnotherOperationInProgress|OperationNotAllowed"; then
      echo "[$vnet] recovery PUT transiently failed on attempt $attempt/10: $update_out"
    else
      echo "[$vnet] recovery PUT failed: $update_out" >&2
      return "$update_rc"
    fi
    sleep 30
  done

  echo "[$vnet] failed to recover after 10 PUT attempts." >&2
  return 1
}

reconcile_vnet() {
  local vnet="${1:?VNet name is required}"
  local initial_state="${2:-}"
  local marker="${3:?marker path is required}"
  local wait_rc=0

  if [ "$initial_state" != "Succeeded" ]; then
    wait_for_vnet "$vnet" || wait_rc=$?
    if [ "$wait_rc" -eq 2 ]; then
      echo "absent" >"$marker"
      return 0
    fi
    if [ "$wait_rc" -ne 0 ]; then
      recover_failed_vnet "$vnet"
    fi
  fi
  echo "ready" >"$marker"
}

wait_batch() {
  local index
  for index in "${!reconcile_pids[@]}"; do
    if ! wait "${reconcile_pids[$index]}"; then
      reconcile_failures=$((reconcile_failures + 1))
    fi
    cat "${reconcile_logs[$index]}"
    rm -f "${reconcile_logs[$index]}"
  done
  reconcile_pids=()
  reconcile_logs=()
}

vnet_names=()
vnet_roles=()
vnet_ids=()
vnet_addresses=()
vnet_markers=()
reconcile_pids=()
reconcile_logs=()
reconcile_failures=0

while IFS=$'\t' read -r vnet role resource_id initial_state; do
  if [ -z "$vnet" ] || [ "$vnet" = "None" ] ||
    [ -z "$role" ] || [ "$role" = "None" ] ||
    [ -z "$resource_id" ] || [ "$resource_id" = "None" ]; then
    echo "VNet inventory row is incomplete: $vnet $role $resource_id $initial_state" >&2
    exit 1
  fi
  address="module.virtual_network[\"$role\"].azurerm_virtual_network.vnet"
  marker=$(mktemp "${TMPDIR:-/tmp}/vnet-reconcile-${role}-XXXXXX.status")
  log_file=$(mktemp "${TMPDIR:-/tmp}/vnet-reconcile-${role}-XXXXXX.log")
  vnet_names+=("$vnet")
  vnet_roles+=("$role")
  vnet_ids+=("$resource_id")
  vnet_addresses+=("$address")
  vnet_markers+=("$marker")
  reconcile_vnet "$vnet" "$initial_state" "$marker" >"$log_file" 2>&1 &
  reconcile_pids+=("$!")
  reconcile_logs+=("$log_file")
  if [ "${#reconcile_pids[@]}" -ge "$reconcile_concurrency" ]; then
    wait_batch
  fi
done < <(printf '%s\n' "$vnet_rows_output")
wait_batch

if [ "$reconcile_failures" -ne 0 ]; then
  rm -f "${vnet_markers[@]}"
  echo "Failed to reconcile $reconcile_failures run-owned VNet(s)." >&2
  exit 1
fi

# Terraform state writes are intentionally sequential.
for index in "${!vnet_names[@]}"; do
  marker_state=$(cat "${vnet_markers[$index]}")
  rm -f "${vnet_markers[$index]}"
  if [ "$marker_state" = "absent" ]; then
    continue
  fi
  vnet="${vnet_names[$index]}"
  address="${vnet_addresses[$index]}"
  resource_id="${vnet_ids[$index]}"
  if printf '%s\n' "$state_list" | grep -Fxq "$address"; then
    echo "[$vnet] already tracked at $address."
    continue
  fi
  echo "[$vnet] importing ambiguous Azure create into $address."
  terraform import \
    -input=false \
    -no-color \
    -var-file "$TERRAFORM_INPUT_FILE" \
    -var "json_input=$TERRAFORM_INPUT_VARIABLES" \
    "$address" \
    "$resource_id"
  state_list="${state_list}${state_list:+$'\n'}${address}"
done

echo "Run-owned VNet pre-apply reconciliation complete."
