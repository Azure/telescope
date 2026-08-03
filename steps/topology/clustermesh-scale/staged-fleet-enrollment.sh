#!/usr/bin/env bash

set -euo pipefail

staged_join_enabled="${CMP_STAGED_JOIN_ENABLED:-false}"
if [ "${staged_join_enabled,,}" != "true" ]; then
  echo "[staged-join] disabled; Fleet members retain their Terraform-created labels"
  exit 0
fi

clusters_file="${CLUSTERS_FILE:-$HOME/.kube/clustermesh-clusters.json}"
fleet_rg="${FLEET_RG:?FLEET_RG is required}"
fleet_name="${FLEET_NAME:?FLEET_NAME is required}"
fleet_profile="${FLEET_PROFILE:?FLEET_PROFILE is required}"
label_key="${CMP_MEMBER_LABEL_KEY:-mesh}"
label_value="${CMP_MEMBER_LABEL_VALUE:-true}"
batch_size="${CMP_STAGED_JOIN_BATCH_SIZE:-10}"
batch_wait_seconds="${CMP_STAGED_JOIN_BATCH_WAIT_SECONDS:-7200}"
total_wait_seconds="${CMP_STAGED_JOIN_TOTAL_WAIT_SECONDS:-21600}"
poll_seconds="${CMP_STAGED_JOIN_POLL_SECONDS:-20}"
check_concurrency="${CMP_STAGED_JOIN_CHECK_CONCURRENCY:-10}"
member_update_attempts="${CMP_STAGED_JOIN_MEMBER_UPDATE_ATTEMPTS:-5}"
apply_attempts="${CMP_STAGED_JOIN_APPLY_ATTEMPTS:-5}"
command_timeout_seconds="${CMP_STAGED_JOIN_COMMAND_TIMEOUT_SECONDS:-900}"
query_timeout_seconds="${CMP_STAGED_JOIN_QUERY_TIMEOUT_SECONDS:-60}"
reapply_seconds="${CMP_STAGED_JOIN_REAPPLY_SECONDS:-300}"
summary_file="${CMP_STAGED_JOIN_SUMMARY_FILE:-$(pwd)/clustermeshprofile-staged-join.json}"

require_positive_integer() {
  local name="$1"
  local value="$2"

  if ! [[ "$value" =~ ^[1-9][0-9]*$ ]]; then
    echo "##vso[task.logissue type=error;] [staged-join] $name must be a positive integer, got '$value'"
    exit 1
  fi
}

for setting in \
  "CMP_STAGED_JOIN_BATCH_SIZE:$batch_size" \
  "CMP_STAGED_JOIN_BATCH_WAIT_SECONDS:$batch_wait_seconds" \
  "CMP_STAGED_JOIN_TOTAL_WAIT_SECONDS:$total_wait_seconds" \
  "CMP_STAGED_JOIN_POLL_SECONDS:$poll_seconds" \
  "CMP_STAGED_JOIN_CHECK_CONCURRENCY:$check_concurrency" \
  "CMP_STAGED_JOIN_MEMBER_UPDATE_ATTEMPTS:$member_update_attempts" \
  "CMP_STAGED_JOIN_APPLY_ATTEMPTS:$apply_attempts" \
  "CMP_STAGED_JOIN_COMMAND_TIMEOUT_SECONDS:$command_timeout_seconds" \
  "CMP_STAGED_JOIN_QUERY_TIMEOUT_SECONDS:$query_timeout_seconds" \
  "CMP_STAGED_JOIN_REAPPLY_SECONDS:$reapply_seconds"; do
  require_positive_integer "${setting%%:*}" "${setting#*:}"
done

if [ ! -s "$clusters_file" ]; then
  echo "##vso[task.logissue type=error;] [staged-join] cluster inventory is missing or empty: $clusters_file"
  exit 1
fi

mapfile -t roles < <(
  jq -er '
    if length == 0 then error("empty cluster inventory") else . end
    | sort_by(.role | ltrimstr("mesh-") | tonumber)
    | .[].role
  ' "$clusters_file"
)

total_members="${#roles[@]}"
if [ "$total_members" -eq 0 ]; then
  echo "##vso[task.logissue type=error;] [staged-join] cluster inventory contains no sortable mesh roles"
  exit 1
fi

started_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
mkdir -p "$(dirname "$summary_file")"
jq -n \
  --arg started_at "$started_at" \
  --arg fleet "$fleet_name" \
  --arg profile "$fleet_profile" \
  --arg selector_label_value "${label_key}=${label_value}" \
  --argjson total_members "$total_members" \
  --argjson batch_size "$batch_size" \
  '{
    status: "in_progress",
    started_at: $started_at,
    fleet: $fleet,
    profile: $profile,
    selector_label: $selector_label_value,
    total_members: $total_members,
    batch_size: $batch_size,
    joined_members: 0,
    batches: []
  }' > "$summary_file"

mark_unexpected_failure() {
  local rc=$?
  local failed_at tmp

  if [ "$rc" -ne 0 ] && [ -s "$summary_file" ]; then
    failed_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    tmp="$(mktemp "${summary_file}.tmp.XXXXXX")"
    jq \
      --arg failed_at "$failed_at" \
      '.status = "failed" | .finished_at = $failed_at' \
      "$summary_file" > "$tmp" || true
    if [ -s "$tmp" ]; then
      mv -f "$tmp" "$summary_file"
    else
      rm -f "$tmp"
    fi
  fi
  return "$rc"
}
trap mark_unexpected_failure EXIT

batch_deadline=0
staged_join_deadline=$(( $(date +%s) + total_wait_seconds ))

remaining_batch_timeout() {
  local requested="$1"
  local remaining

  remaining=$((batch_deadline - $(date +%s)))
  if [ "$remaining" -le 0 ]; then
    return 1
  fi
  if [ "$remaining" -lt "$requested" ]; then
    printf '%s\n' "$remaining"
  else
    printf '%s\n' "$requested"
  fi
}

update_summary() {
  local status="$1"
  local batch_number="$2"
  local joined_count="$3"
  local batch_started_at="$4"
  local batch_finished_at="$5"
  shift 5
  local batch_roles=("$@")
  local tmp

  tmp="$(mktemp "${summary_file}.tmp.XXXXXX")"
  jq \
    --arg status "$status" \
    --arg batch_started_at "$batch_started_at" \
    --arg batch_finished_at "$batch_finished_at" \
    --argjson batch_number "$batch_number" \
    --argjson joined_count "$joined_count" \
    --argjson batch_roles "$(printf '%s\n' "${batch_roles[@]}" | jq -R . | jq -s .)" \
    '
      .status = $status
      | .joined_members = $joined_count
      | .batches += [{
          batch: $batch_number,
          members: $batch_roles,
          started_at: $batch_started_at,
          finished_at: $batch_finished_at,
          status: (if $status == "failed" then "failed" else "succeeded" end)
        }]
      | if $status == "succeeded" or $status == "failed"
        then .finished_at = $batch_finished_at
        else .
        end
    ' "$summary_file" > "$tmp"
  mv -f "$tmp" "$summary_file"
}

run_member_update() {
  local role="$1"
  local attempt output rc timeout_seconds

  for attempt in $(seq 1 "$member_update_attempts"); do
    timeout_seconds=$(remaining_batch_timeout "$command_timeout_seconds") || return 1
    rc=0
    output=$(timeout "${timeout_seconds}s" az fleet member update \
      --resource-group "$fleet_rg" \
      --fleet-name "$fleet_name" \
      --name "$role" \
      --labels "${label_key}=${label_value}" \
      --output none \
      --only-show-errors 2>&1) || rc=$?
    if [ "$rc" -eq 0 ]; then
      echo "[staged-join] selected $role with ${label_key}=${label_value}"
      return 0
    fi

    echo "[staged-join] member update failed for $role on attempt $attempt/$member_update_attempts (exit=$rc): $output"
    if echo "$output" | grep -Eqi 'AuthorizationFailed|Forbidden|SubscriptionNotFound|ResourceGroupNotFound|ResourceNotFound'; then
      return 1
    fi
    if [ "$attempt" -lt "$member_update_attempts" ]; then
      sleep "$poll_seconds"
    fi
  done

  return 1
}

apply_profile() {
  local attempt output rc timeout_seconds

  for attempt in $(seq 1 "$apply_attempts"); do
    timeout_seconds=$(remaining_batch_timeout "$command_timeout_seconds") || return 1
    rc=0
    output=$(timeout "${timeout_seconds}s" az fleet clustermeshprofile apply \
      --resource-group "$fleet_rg" \
      --fleet-name "$fleet_name" \
      --name "$fleet_profile" \
      --output none \
      --only-show-errors 2>&1) || rc=$?
    if [ "$rc" -eq 0 ]; then
      echo "[staged-join] profile apply accepted on attempt $attempt/$apply_attempts"
      return 0
    fi

    echo "[staged-join] profile apply failed on attempt $attempt/$apply_attempts (exit=$rc): $output"
    if echo "$output" | grep -Eqi 'AuthorizationFailed|Forbidden|SubscriptionNotFound|ResourceGroupNotFound|ResourceNotFound'; then
      return 1
    fi
    if [ "$rc" -eq 124 ] ||
      echo "$output" | grep -Eqi 'ResourceNotFinalState|OperationNotAllowed|AnotherOperationInProgress'; then
      echo "[staged-join] profile apply is still active; continuing with bounded readiness polling"
      return 0
    fi
    if [ "$attempt" -lt "$apply_attempts" ]; then
      sleep "$poll_seconds"
    fi
  done

  return 1
}

applied_member_count() {
  profile_member_count 'length(@)'
}

connected_member_count() {
  profile_member_count "length([?meshProperties.status.state=='Connected'])"
}

profile_member_count() {
  local query="$1"
  local output rc count

  rc=0
  output=$(timeout "${query_timeout_seconds}s" az fleet clustermeshprofile list-members \
    --resource-group "$fleet_rg" \
    --fleet-name "$fleet_name" \
    --name "$fleet_profile" \
    --query "$query" \
    --output tsv \
    --only-show-errors 2>&1) || rc=$?
  if [ "$rc" -ne 0 ]; then
    echo "[staged-join] profile-member query failed (exit=$rc): $output" >&2
    return 1
  fi

  count=$(printf '%s\n' "$output" |
    awk '/^[[:space:]]*[0-9]+[[:space:]]*$/ { value=$1 } END { print value }')
  if ! [[ "$count" =~ ^[0-9]+$ ]]; then
    echo "[staged-join] profile-member query returned no numeric count: $output" >&2
    return 1
  fi

  printf '%s\n' "$count"
}

profile_provisioning_state() {
  local output rc state

  rc=0
  output=$(timeout "${query_timeout_seconds}s" az fleet clustermeshprofile show \
    --resource-group "$fleet_rg" \
    --fleet-name "$fleet_name" \
    --name "$fleet_profile" \
    --query properties.provisioningState \
    --output tsv \
    --only-show-errors 2>&1) || rc=$?
  if [ "$rc" -ne 0 ]; then
    echo "[staged-join] profile-state query failed (exit=$rc): $output" >&2
    return 1
  fi

  state=$(printf '%s\n' "$output" |
    awk '/^[[:space:]]*(Succeeded|Failed|Applying|Updating|Creating)[[:space:]]*$/ { value=$1 } END { print value }')
  if [ -z "$state" ]; then
    echo "[staged-join] profile-state query returned no recognized state: $output" >&2
    return 1
  fi

  printf '%s\n' "$state"
}

check_member() {
  local role="$1"
  local expected_remote="$2"
  local kubeconfig="$HOME/.kube/$role.config"
  local available ip status peer_counts ready total timeout_seconds

  timeout_seconds=$(remaining_batch_timeout 45) || {
    echo "$role batch deadline exhausted before Deployment check"
    return 1
  }
  available=$(KUBECONFIG="$kubeconfig" timeout "${timeout_seconds}s" kubectl -n kube-system \
    get deployment clustermesh-apiserver \
    -o jsonpath='{.status.conditions[?(@.type=="Available")].status}' 2>/dev/null || true)
  timeout_seconds=$(remaining_batch_timeout 45) || {
    echo "$role batch deadline exhausted before Service check"
    return 1
  }
  ip=$(KUBECONFIG="$kubeconfig" timeout "${timeout_seconds}s" kubectl -n kube-system \
    get service clustermesh-apiserver \
    -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>/dev/null || true)
  if [ "$available" != "True" ] || [ -z "$ip" ]; then
    echo "$role deployment=${available:-<none>} lb=${ip:-<none>}"
    return 1
  fi

  timeout_seconds=$(remaining_batch_timeout 60) || {
    echo "$role batch deadline exhausted before Cilium check"
    return 1
  }
  status=$(KUBECONFIG="$kubeconfig" timeout "${timeout_seconds}s" kubectl -n kube-system \
    exec ds/cilium -- cilium-dbg status 2>/dev/null || true)
  peer_counts=$(
    printf '%s\n' "$status" |
      sed -nE 's/.*ClusterMesh:[[:space:]]+([0-9]+)\/([0-9]+) remote clusters ready.*/\1 \2/p' |
      head -1
  )
  ready="${peer_counts%% *}"
  total="${peer_counts#* }"
  ready="${ready:-0}"
  total="${total:-0}"
  if [ "$ready" -lt "$expected_remote" ] || [ "$total" -lt "$expected_remote" ]; then
    echo "$role deployment=True lb=$ip peers=${ready}/${total} expected=${expected_remote}"
    return 1
  fi

  echo "$role deployment=True lb=$ip peers=${ready}/${total}"
}

check_joined_members() {
  local expected_remote="$1"
  shift
  local joined_roles=("$@")
  local status_dir pids=() pid role failures=0

  status_dir="$(mktemp -d)"
  for role in "${joined_roles[@]}"; do
    (
      if check_member "$role" "$expected_remote" > "$status_dir/$role"; then
        touch "$status_dir/$role.ready"
      fi
    ) &
    pids+=("$!")

    if [ "${#pids[@]}" -ge "$check_concurrency" ]; then
      for pid in "${pids[@]}"; do
        wait "$pid"
      done
      pids=()
    fi
  done
  for pid in "${pids[@]}"; do
    wait "$pid"
  done

  for role in "${joined_roles[@]}"; do
    if [ ! -f "$status_dir/$role.ready" ]; then
      cat "$status_dir/$role" 2>/dev/null || echo "$role check produced no status"
      failures=$((failures + 1))
    fi
  done
  rm -rf "$status_dir"
  [ "$failures" -eq 0 ]
}

echo "[staged-join] enrolling $total_members Fleet members in batches of $batch_size"
joined=()
batch=()
batch_number=0

run_batch() {
  local batch_started_at batch_finished_at next_reapply
  local applied connected profile_state expected_remote

  if [ "${#batch[@]}" -eq 0 ]; then
    return 0
  fi

  batch_number=$((batch_number + 1))
  batch_started_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  batch_deadline=$(( $(date +%s) + batch_wait_seconds ))
  if [ "$batch_deadline" -gt "$staged_join_deadline" ]; then
    batch_deadline="$staged_join_deadline"
  fi
  if [ "$(date +%s)" -ge "$batch_deadline" ]; then
    echo "##vso[task.logissue type=error;] [staged-join] total staged enrollment budget exhausted before batch #$batch_number"
    return 1
  fi
  echo "[staged-join] batch #$batch_number selecting ${#batch[@]} member(s): ${batch[*]}"

  for role in "${batch[@]}"; do
    if ! run_member_update "$role"; then
      batch_finished_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
      update_summary "failed" "$batch_number" "${#joined[@]}" \
        "$batch_started_at" "$batch_finished_at" "${batch[@]}"
      echo "##vso[task.logissue type=error;] [staged-join] failed to select Fleet member $role"
      return 1
    fi
  done

  joined+=("${batch[@]}")
  if ! apply_profile; then
    batch_finished_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    update_summary "failed" "$batch_number" "${#joined[@]}" \
      "$batch_started_at" "$batch_finished_at" "${batch[@]}"
    echo "##vso[task.logissue type=error;] [staged-join] profile apply failed for batch #$batch_number"
    return 1
  fi

  next_reapply=$(( $(date +%s) + reapply_seconds ))
  expected_remote=$((${#joined[@]} - 1))
  while [ "$(date +%s)" -lt "$batch_deadline" ]; do
    applied=""
    connected=""
    profile_state=""
    applied=$(applied_member_count || true)
    connected=$(connected_member_count || true)
    profile_state=$(profile_provisioning_state || true)
    if [ "$applied" = "${#joined[@]}" ] &&
      [ "$connected" = "${#joined[@]}" ] &&
      [ "$profile_state" = "Succeeded" ] &&
      check_joined_members "$expected_remote" "${joined[@]}" &&
      [ "$(date +%s)" -lt "$batch_deadline" ]; then
      batch_finished_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
      update_summary "in_progress" "$batch_number" "${#joined[@]}" \
        "$batch_started_at" "$batch_finished_at" "${batch[@]}"
      echo "[staged-join] batch #$batch_number converged: ${#joined[@]}/$total_members members applied, all apiservers/LBs ready, all members connected to $expected_remote peers"
      batch=()
      return 0
    fi

    echo "[staged-join] batch #$batch_number waiting: applied=${applied:-unknown}/${#joined[@]}, connected=${connected:-unknown}/${#joined[@]}, profile=${profile_state:-unknown}, expected_remote=$expected_remote"
    if [ "$(date +%s)" -ge "$next_reapply" ]; then
      echo "[staged-join] re-applying profile while batch #$batch_number converges"
      apply_profile || true
      next_reapply=$(( $(date +%s) + reapply_seconds ))
    fi
    sleep "$poll_seconds"
  done

  batch_finished_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  update_summary "failed" "$batch_number" "${#joined[@]}" \
    "$batch_started_at" "$batch_finished_at" "${batch[@]}"
  echo "##vso[task.logissue type=error;] [staged-join] batch #$batch_number did not converge before its bounded deadline (batch_limit=${batch_wait_seconds}s total_limit=${total_wait_seconds}s)"
  return 1
}

for role in "${roles[@]}"; do
  batch+=("$role")
  if [ "${#batch[@]}" -ge "$batch_size" ]; then
    run_batch
  fi
done
run_batch

finished_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
tmp="$(mktemp "${summary_file}.tmp.XXXXXX")"
jq \
  --arg finished_at "$finished_at" \
  '.status = "succeeded" | .finished_at = $finished_at' \
  "$summary_file" > "$tmp"
mv -f "$tmp" "$summary_file"
trap - EXIT
echo "[staged-join] complete: all $total_members members enrolled and connected"
