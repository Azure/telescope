#!/usr/bin/env bash
set -euo pipefail

: "${ARM_SUBSCRIPTION_ID:?ARM_SUBSCRIPTION_ID is required}"
: "${RUN_ID:?RUN_ID is required}"
: "${REGION:?REGION is required}"

cleanup_concurrency="${AKS_FAILED_CLUSTER_CLEANUP_CONCURRENCY:-10}"
delete_timeout="${AKS_FAILED_CLUSTER_DELETE_TIMEOUT_SECONDS:-1800}"
poll_seconds="${AKS_FAILED_CLUSTER_DELETE_POLL_SECONDS:-20}"
delete_transition_timeout="${AKS_FAILED_CLUSTER_DELETE_TRANSITION_SECONDS:-120}"
marker_root="$HOME/.telescope/aks-recovery/$RUN_ID"

for value in \
  "$cleanup_concurrency" \
  "$delete_timeout" \
  "$poll_seconds" \
  "$delete_transition_timeout"; do
  if ! [[ "$value" =~ ^[1-9][0-9]*$ ]]; then
    echo "Failed-AKS cleanup settings must be positive integers." >&2
    exit 1
  fi
done

state_rc=0
state_list=$(terraform state list 2>&1) || state_rc=$?
if [ "$state_rc" -ne 0 ]; then
  if echo "$state_list" | grep -qi "No state file was found"; then
    state_list=""
  else
    echo "Failed to read Terraform state before AKS cleanup: $state_list" >&2
    exit "$state_rc"
  fi
fi

state_json='{}'
if [ -n "$state_list" ]; then
  show_rc=0
  state_json=$(terraform show -json 2>&1) || show_rc=$?
  if [ "$show_rc" -ne 0 ]; then
    echo "Failed to read Terraform state JSON before AKS cleanup: $state_json" >&2
    exit "$show_rc"
  fi
fi

absent_state_clusters=()
declare -A cluster_roles=()
declare -A actual_clusters=()
expected_rows_output=$(printf '%s' "$state_json" | jq -r '
  .. | objects
  | select(
      .type? == "terraform_data"
      and .name? == "aks_cli"
      and (.values.input.aks_name? | type) == "string"
      and (.values.input.role? | type) == "string"
    )
  | [.values.input.aks_name, .values.input.role]
  | @tsv
')

cluster_inventory_output=""
inventory_ok=false
inventory_error_file=$(mktemp "${TMPDIR:-/tmp}/aks-inventory-XXXXXX.err")
for inventory_attempt in $(seq 1 5); do
  : >"$inventory_error_file"
  list_rc=0
  cluster_inventory_output=$(timeout 120s az aks list \
    --subscription "$ARM_SUBSCRIPTION_ID" \
    --resource-group "$RUN_ID" \
    --query "[?location=='$REGION' && tags.telescope_provisioner=='aks-cli'].[name,tags.role,provisioningState]" \
    --output tsv \
    --only-show-errors 2>"$inventory_error_file") || list_rc=$?
  inventory_error=$(cat "$inventory_error_file")
  inventory_failure_output="$inventory_error"
  if [ -z "$inventory_failure_output" ]; then
    inventory_failure_output="$cluster_inventory_output"
  fi
  if [ "$list_rc" -eq 0 ]; then
    inventory_ok=true
    break
  fi
  if [ "$list_rc" -eq 124 ] || [ "$list_rc" -eq 137 ] ||
    echo "$inventory_failure_output" |
      grep -qiE "TooManyRequests|429|RetryableError|ServerTimeout|ServiceUnavailable|temporarily unavailable|connection reset|timed out"; then
    echo "AKS inventory attempt $inventory_attempt/5 failed transiently: $inventory_failure_output"
    sleep $((inventory_attempt * 10))
    continue
  fi
  echo "Failed to enumerate AKS clusters in $RUN_ID: $inventory_failure_output" >&2
  rm -f "$inventory_error_file"
  exit "$list_rc"
done
rm -f "$inventory_error_file"
if [ "$inventory_ok" != "true" ]; then
  echo "Failed to enumerate AKS clusters in $RUN_ID after 5 attempts." >&2
  exit 1
fi

cluster_rows=()
if [ -n "$cluster_inventory_output" ]; then
  while IFS=$'\t' read -r cluster role state; do
    if [ -z "$cluster" ] || [ "$cluster" = "None" ] ||
      [ -z "$role" ] || [ "$role" = "None" ]; then
      echo "AKS inventory row is missing cluster name or role tag: $cluster $role $state" >&2
      exit 1
    fi
    actual_clusters["$cluster"]="$state"
    case "$state" in
      Failed|Canceled|Updating|Creating)
        cluster_rows+=("$cluster"$'\t'"$role"$'\t'"$state")
        ;;
    esac
  done < <(printf '%s\n' "$cluster_inventory_output")
fi

if [ -n "$expected_rows_output" ]; then
  while IFS=$'\t' read -r cluster role; do
    if [ -z "${actual_clusters[$cluster]+x}" ]; then
      echo "[$cluster] Azure resource is absent but Terraform create state remains; resetting stale state."
      absent_state_clusters+=("$cluster")
      cluster_roles["$cluster"]="$role"
    fi
  done < <(printf '%s\n' "$expected_rows_output")
fi

if [ "${#cluster_rows[@]}" -eq 0 ] &&
  [ "${#absent_state_clusters[@]}" -eq 0 ]; then
  echo "No Failed, Canceled, Updating, or Creating AKS clusters require pre-apply cleanup."
  exit 0
fi

cleanup_clusters=()
declare -A cluster_states=()
for row in "${cluster_rows[@]}"; do
  IFS=$'\t' read -r cluster role state <<<"$row"
  if [ -z "$cluster" ] || [ "$cluster" = "None" ] ||
    [ -z "$role" ] || [ "$role" = "None" ]; then
    echo "Unhealthy AKS row is missing cluster name or role tag: $row" >&2
    exit 1
  fi
  if [ "$state" = "Updating" ] || [ "$state" = "Creating" ]; then
    marker_file="$marker_root/$cluster.stuck"
    if [ ! -s "$marker_file" ]; then
      echo "[$cluster] $state without a stuck marker; leaving it intact."
      continue
    fi
    echo "[$cluster] $state with waiter marker $(cat "$marker_file"); treating as stuck."
  fi
  cleanup_clusters+=("$cluster")
  cluster_roles["$cluster"]="$role"
  cluster_states["$cluster"]="$state"
done

if [ "${#cleanup_clusters[@]}" -eq 0 ] &&
  [ "${#absent_state_clusters[@]}" -eq 0 ]; then
  echo "No terminal Failed/Canceled or marked stuck AKS clusters require cleanup."
  exit 0
fi

if [ "${#cleanup_clusters[@]}" -gt 0 ]; then
  echo "Pre-apply cleanup found ${#cleanup_clusters[@]} unhealthy AKS cluster(s): ${cleanup_clusters[*]}"
fi

cleanup_cluster() {
  local cluster="${1:?cluster name is required}"
  local initial_state="${2:?initial provisioning state is required}"
  local attempt delete_accepted=false delete_out delete_rc
  local deadline delete_started show_out show_rc state transitioned=false

  for attempt in $(seq 1 10); do
    delete_rc=0
    delete_out=$(timeout 120s az aks delete \
      --subscription "$ARM_SUBSCRIPTION_ID" \
      --resource-group "$RUN_ID" \
      --name "$cluster" \
      --yes \
      --no-wait \
      --only-show-errors 2>&1) || delete_rc=$?
    if [ "$delete_rc" -eq 0 ]; then
      echo "[$cluster] delete accepted on attempt $attempt/10."
      delete_accepted=true
      break
    fi
    if echo "$delete_out" |
      grep -qiE "NotFound|ResourceNotFound|ResourceGroupNotFound|could not be found"; then
      echo "[$cluster] already absent."
      return 0
    fi
    if echo "$delete_out" |
      grep -qiE "OperationNotAllowed|AnotherOperationInProgress|RetryableError|ServerTimeout|ServiceUnavailable"; then
      echo "[$cluster] delete request transiently blocked on attempt $attempt/10: $delete_out"
      sleep 30
      continue
    fi
    echo "[$cluster] delete request failed: $delete_out" >&2
    return "$delete_rc"
  done

  if [ "$delete_accepted" != "true" ]; then
    echo "[$cluster] delete was not accepted after 10 attempts." >&2
    return 1
  fi

  delete_started=$(date +%s)
  deadline=$((delete_started + delete_timeout))
  while [ "$(date +%s)" -lt "$deadline" ]; do
    show_rc=0
    show_out=$(timeout 120s az aks show \
      --subscription "$ARM_SUBSCRIPTION_ID" \
      --resource-group "$RUN_ID" \
      --name "$cluster" \
      --query provisioningState \
      --output tsv \
      --only-show-errors 2>&1) || show_rc=$?
    if [ "$show_rc" -ne 0 ]; then
      if echo "$show_out" |
        grep -qiE "NotFound|ResourceNotFound|ResourceGroupNotFound|could not be found"; then
        echo "[$cluster] fully deleted."
        return 0
      fi
      echo "[$cluster] delete status check failed transiently: $show_out"
      sleep "$poll_seconds"
      continue
    fi

    state=$(printf '%s' "$show_out" | tr -d '[:space:]')
    if [ "$state" != "$initial_state" ]; then
      transitioned=true
    fi
    if [ "$transitioned" != "true" ] &&
      [ "$state" = "$initial_state" ] &&
      [ $(($(date +%s) - delete_started)) -ge "$delete_transition_timeout" ]; then
      echo "[$cluster] delete was accepted but the cluster remained $initial_state for ${delete_transition_timeout}s." >&2
      return 1
    fi
    echo "[$cluster] deletion in progress (state=${state:-unknown})."
    sleep "$poll_seconds"
  done

  echo "[$cluster] deletion did not complete within ${delete_timeout}s." >&2
  return 1
}

wait_batch() {
  local index
  for index in "${!cleanup_pids[@]}"; do
    if wait "${cleanup_pids[$index]}"; then
      cleaned_clusters+=("${cleanup_batch_clusters[$index]}")
    else
      cleanup_failures=$((cleanup_failures + 1))
    fi
    cat "${cleanup_logs[$index]}"
    rm -f "${cleanup_logs[$index]}"
  done
  cleanup_pids=()
  cleanup_logs=()
  cleanup_batch_clusters=()
}

cleanup_failures=0
cleaned_clusters=("${absent_state_clusters[@]}")
cleanup_pids=()
cleanup_logs=()
cleanup_batch_clusters=()
for cluster in "${cleanup_clusters[@]}"; do
  log_file=$(mktemp "${TMPDIR:-/tmp}/failed-aks-${cluster}-XXXXXX.log")
  cleanup_cluster "$cluster" "${cluster_states[$cluster]}" >"$log_file" 2>&1 &
  cleanup_pids+=("$!")
  cleanup_logs+=("$log_file")
  cleanup_batch_clusters+=("$cluster")
  if [ "${#cleanup_pids[@]}" -ge "$cleanup_concurrency" ]; then
    wait_batch
  fi
done
wait_batch

# terraform_data cannot observe that its CLI-created AKS resource disappeared.
# Remove only the create/wait/extra-pool bookkeeping for each deleted cluster
# so the upcoming apply executes those provisioners again. Provider-managed
# identities, role assignments, and network resources stay in state and
# reconcile normally.
for cluster in "${cleaned_clusters[@]}"; do
  role="${cluster_roles[$cluster]}"
  rm -f "$marker_root/$cluster.stuck"
  state_prefix="module.aks-cli[\"$role\"].terraform_data."
  mapfile -t stale_addresses < <(
    printf '%s\n' "$state_list" |
      grep -F "$state_prefix" |
      grep -E '\.aks_cli$|\.aks_wait_succeeded\[|\.aks_nodepool_cli\[' ||
      true
  )
  if [ "${#stale_addresses[@]}" -eq 0 ]; then
    echo "[$cluster] no stale AKS terraform_data state entries found."
    continue
  fi
  for address in "${stale_addresses[@]}"; do
    echo "[$cluster] removing stale Terraform state: $address"
    terraform state rm "$address"
  done
done

if [ "$cleanup_failures" -ne 0 ]; then
  echo "Failed to clean $cleanup_failures unhealthy AKS cluster(s) before Terraform apply." >&2
  exit 1
fi

echo "Failed/stuck AKS pre-apply cleanup complete."
