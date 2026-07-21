#!/usr/bin/env bash
set -euo pipefail

: "${ARM_SUBSCRIPTION_ID:?ARM_SUBSCRIPTION_ID is required}"
: "${RUN_ID:?RUN_ID is required}"

cleanup_concurrency="${AKS_FAILED_CLUSTER_CLEANUP_CONCURRENCY:-10}"
delete_timeout="${AKS_FAILED_CLUSTER_DELETE_TIMEOUT_SECONDS:-1800}"
poll_seconds="${AKS_FAILED_CLUSTER_DELETE_POLL_SECONDS:-20}"
delete_transition_timeout="${AKS_FAILED_CLUSTER_DELETE_TRANSITION_SECONDS:-120}"

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
list_rc=0
failed_rows_output=$(az aks list \
    --subscription "$ARM_SUBSCRIPTION_ID" \
    --resource-group "$RUN_ID" \
    --query "[?provisioningState=='Failed' && tags.telescope_provisioner=='aks-cli'].[name,tags.role]" \
    --output tsv \
    --only-show-errors) || list_rc=$?
if [ "$list_rc" -ne 0 ]; then
  echo "Failed to enumerate terminal AKS clusters in $RUN_ID." >&2
  exit "$list_rc"
fi

failed_cluster_rows=()
if [ -n "$failed_rows_output" ]; then
  mapfile -t failed_cluster_rows < <(printf '%s\n' "$failed_rows_output")
fi

if [ "${#failed_cluster_rows[@]}" -eq 0 ]; then
  echo "No terminal Failed AKS clusters require pre-apply cleanup."
  exit 0
fi

failed_clusters=()
declare -A cluster_roles=()
for row in "${failed_cluster_rows[@]}"; do
  IFS=$'\t' read -r cluster role <<<"$row"
  if [ -z "$cluster" ] || [ -z "$role" ]; then
    echo "Failed AKS row is missing cluster name or role tag: $row" >&2
    exit 1
  fi
  failed_clusters+=("$cluster")
  cluster_roles["$cluster"]="$role"
done

echo "Pre-apply cleanup found ${#failed_clusters[@]} terminal Failed AKS cluster(s): ${failed_clusters[*]}"

cleanup_cluster() {
  local cluster="${1:?cluster name is required}"
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
    if [ "$state" != "Failed" ]; then
      transitioned=true
    fi
    if [ "$transitioned" != "true" ] &&
      [ "$state" = "Failed" ] &&
      [ $(($(date +%s) - delete_started)) -ge "$delete_transition_timeout" ]; then
      echo "[$cluster] delete was accepted but the cluster remained Failed for ${delete_transition_timeout}s." >&2
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
    if ! wait "${cleanup_pids[$index]}"; then
      cleanup_failures=$((cleanup_failures + 1))
    fi
    cat "${cleanup_logs[$index]}"
    rm -f "${cleanup_logs[$index]}"
  done
  cleanup_pids=()
  cleanup_logs=()
}

cleanup_failures=0
cleanup_pids=()
cleanup_logs=()
for cluster in "${failed_clusters[@]}"; do
  log_file=$(mktemp "${TMPDIR:-/tmp}/failed-aks-${cluster}-XXXXXX.log")
  cleanup_cluster "$cluster" >"$log_file" 2>&1 &
  cleanup_pids+=("$!")
  cleanup_logs+=("$log_file")
  if [ "${#cleanup_pids[@]}" -ge "$cleanup_concurrency" ]; then
    wait_batch
  fi
done
wait_batch

if [ "$cleanup_failures" -ne 0 ]; then
  echo "Failed to clean $cleanup_failures terminal AKS cluster(s) before Terraform apply." >&2
  exit 1
fi

# terraform_data cannot observe that its CLI-created AKS resource disappeared.
# Remove only the create/wait/extra-pool bookkeeping for each deleted cluster
# so the upcoming apply executes those provisioners again. Provider-managed
# identities, role assignments, and network resources stay in state and
# reconcile normally.
for cluster in "${failed_clusters[@]}"; do
  role="${cluster_roles[$cluster]}"
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

echo "Terminal Failed AKS pre-apply cleanup complete."
