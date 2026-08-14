#!/usr/bin/env bash
set -euo pipefail

: "${CLUSTERS_FILE:?CLUSTERS_FILE is required}"
: "${OUTPUT_FILE:?OUTPUT_FILE is required}"
: "${STATE_ROOT:?STATE_ROOT is required}"
: "${TARGET_SUBSCRIPTION_ID:?TARGET_SUBSCRIPTION_ID is required}"

force_reassert="${FORCE_REASSERT:-false}"
repair_enabled="${AKS_CILIUM_POLICY_GUARD_REPAIR_ENABLED:-false}"
timeout_seconds="${AKS_CILIUM_POLICY_GUARD_TIMEOUT_SECONDS:-1800}"
quiet_seconds="${AKS_CILIUM_POLICY_GUARD_QUIET_SECONDS:-300}"
poll_seconds="${AKS_CILIUM_POLICY_GUARD_POLL_SECONDS:-15}"
command_timeout_seconds="${AKS_CILIUM_POLICY_GUARD_COMMAND_TIMEOUT_SECONDS:-900}"
repair_marker="$STATE_ROOT/repair-used"

for value_name in \
  timeout_seconds \
  quiet_seconds \
  poll_seconds \
  command_timeout_seconds; do
  value="${!value_name}"
  if ! [[ "$value" =~ ^[0-9]+$ ]]; then
    echo "${value_name} must be a non-negative integer." >&2
    exit 1
  fi
done
if [ "$poll_seconds" -lt 1 ] || [ "$command_timeout_seconds" -lt 1 ]; then
  echo "poll_seconds and command_timeout_seconds must be at least 1." >&2
  exit 1
fi
if [ ! -s "$CLUSTERS_FILE" ]; then
  echo "Cluster inventory not found at $CLUSTERS_FILE" >&2
  exit 1
fi
cluster_count=$(jq 'length' "$CLUSTERS_FILE")
if [ "$cluster_count" -lt 1 ]; then
  echo "Cluster inventory contains no clusters." >&2
  exit 1
fi

mkdir -p "$(dirname "$OUTPUT_FILE")" "$STATE_ROOT"
started_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)
before_file=$(mktemp)
after_file=$(mktemp)
repair_needed=false
drift_detected=false

capture_cluster_state() {
  local cluster="$1"
  local role name resource_group kubeconfig profile cm_json ds_json
  local network_policy network_dataplane provisioning_state policy_mode
  local desired ready updated observed generation checksum
  role=$(jq -r '.role' <<<"$cluster")
  name=$(jq -r '.name' <<<"$cluster")
  resource_group=$(jq -r '.rg' <<<"$cluster")
  kubeconfig="$HOME/.kube/$role.config"

  profile=$(az aks show \
    --subscription "$TARGET_SUBSCRIPTION_ID" \
    --resource-group "$resource_group" \
    --name "$name" \
    --query '{
      networkPolicy: networkProfile.networkPolicy,
      networkDataplane: networkProfile.networkDataplane,
      provisioningState: provisioningState
    }' -o json 2>/dev/null || echo '{}')
  cm_json=$(KUBECONFIG="$kubeconfig" kubectl -n kube-system \
    get configmap cilium-config -o json 2>/dev/null || echo '{}')
  ds_json=$(KUBECONFIG="$kubeconfig" kubectl -n kube-system \
    get daemonset cilium -o json 2>/dev/null || echo '{}')

  network_policy=$(jq -r '.networkPolicy // ""' <<<"$profile")
  network_dataplane=$(jq -r '.networkDataplane // ""' <<<"$profile")
  provisioning_state=$(jq -r '.provisioningState // ""' <<<"$profile")
  policy_mode=$(jq -r '.data["enable-policy"] // ""' <<<"$cm_json")
  desired=$(jq -r '.status.desiredNumberScheduled // 0' <<<"$ds_json")
  ready=$(jq -r '.status.numberReady // 0' <<<"$ds_json")
  updated=$(jq -r '.status.updatedNumberScheduled // 0' <<<"$ds_json")
  observed=$(jq -r '.status.observedGeneration // 0' <<<"$ds_json")
  generation=$(jq -r '.metadata.generation // 0' <<<"$ds_json")
  checksum=$(jq -r \
    '.spec.template.metadata.annotations["cilium.io/cilium-configmap-checksum"] // ""' \
    <<<"$ds_json")

  jq -cn \
    --arg role "$role" \
    --arg name "$name" \
    --arg resource_group "$resource_group" \
    --arg network_policy "$network_policy" \
    --arg network_dataplane "$network_dataplane" \
    --arg provisioning_state "$provisioning_state" \
    --arg policy_mode "$policy_mode" \
    --arg checksum "$checksum" \
    --argjson desired "$desired" \
    --argjson ready "$ready" \
    --argjson updated "$updated" \
    --argjson observed "$observed" \
    --argjson generation "$generation" \
    '{
      role: $role,
      name: $name,
      resource_group: $resource_group,
      network_policy: $network_policy,
      network_dataplane: $network_dataplane,
      provisioning_state: $provisioning_state,
      policy_mode: $policy_mode,
      cilium: {
        desired: $desired,
        ready: $ready,
        updated: $updated,
        observed_generation: $observed,
        generation: $generation,
        config_checksum: $checksum
      }
    }'
}

state_is_healthy() {
  jq -e '
    .network_policy == "cilium"
    and .network_dataplane == "cilium"
    and .provisioning_state == "Succeeded"
    and .policy_mode == "default"
    and .cilium.desired > 0
    and .cilium.ready == .cilium.desired
    and .cilium.updated == .cilium.desired
    and .cilium.observed_generation == .cilium.generation
  ' >/dev/null
}

while IFS= read -r cluster; do
  state=$(capture_cluster_state "$cluster")
  echo "$state" >>"$before_file"
  role=$(jq -r '.role' <<<"$state")
  network_policy=$(jq -r '.network_policy' <<<"$state")
  network_dataplane=$(jq -r '.network_dataplane' <<<"$state")
  policy_mode=$(jq -r '.policy_mode' <<<"$state")
  if [ "$network_policy" != "cilium" ] ||
     [ "$network_dataplane" != "cilium" ]; then
    echo "[$role] AKS network profile is not Cilium policy+dataplane: policy=${network_policy:-missing} dataplane=${network_dataplane:-missing}" >&2
    rm -f "$before_file" "$after_file"
    exit 1
  fi
  if ! state_is_healthy <<<"$state"; then
    repair_needed=true
    if [ "$policy_mode" != "default" ]; then
      drift_detected=true
    fi
  fi
done < <(jq -c 'sort_by(.role)[]' "$CLUSTERS_FILE")

if [ "${force_reassert,,}" = "true" ]; then
  repair_needed=true
fi
if [ "$drift_detected" = "true" ] && [ -e "$repair_marker" ]; then
  echo "Cilium policy drift recurred after the bounded AKS repair; refusing another reconciliation loop." >&2
  jq -n \
    --arg started_at "$started_at" \
    --argjson before "$(jq -s '.' "$before_file")" \
    '{
      schema_version: 1,
      started_at: $started_at,
      success: false,
      repaired: false,
      reason: "policy_drift_recurred",
      before: $before
    }' >"$OUTPUT_FILE"
  rm -f "$before_file" "$after_file"
  exit 1
fi

if [ "$repair_needed" = "true" ] &&
   [ "${repair_enabled,,}" != "true" ]; then
  jq -n \
    --arg started_at "$started_at" \
    --argjson drift_detected "$drift_detected" \
    --argjson before "$(jq -s '.' "$before_file")" \
    '{
      schema_version: 1,
      started_at: $started_at,
      success: false,
      repaired: false,
      drift_detected: $drift_detected,
      reason: "cilium_policy_or_rollout_drift",
      before: $before
    }' >"$OUTPUT_FILE"
  rm -f "$before_file" "$after_file"
  echo "Cilium policy or rollout drift detected; supported AKS reassertion is disabled because build 75469 proved it does not restore enable-policy=default." >&2
  exit 1
fi

if [ "$repair_needed" != "true" ]; then
  before=$(jq -s '.' "$before_file")
  jq -n \
    --arg started_at "$started_at" \
    --arg observed_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    --argjson before "$before" \
    '{
      schema_version: 1,
      started_at: $started_at,
      observed_at: $observed_at,
      success: true,
      repaired: false,
      drift_detected: false,
      before: $before,
      after: $before
    }' >"$OUTPUT_FILE"
  rm -f "$before_file" "$after_file"
  echo "Cilium policy guard passed for $cluster_count cluster(s); no repair needed"
  exit 0
fi

repaired=false
repaired=true
while IFS= read -r cluster; do
  role=$(jq -r '.role' <<<"$cluster")
  name=$(jq -r '.name' <<<"$cluster")
  resource_group=$(jq -r '.rg' <<<"$cluster")
  echo "[$role] reasserting AKS Cilium policy, dataplane, and ACNS configuration"
  if ! timeout "${command_timeout_seconds}s" az aks update \
      --subscription "$TARGET_SUBSCRIPTION_ID" \
      --resource-group "$resource_group" \
      --name "$name" \
      --network-dataplane cilium \
      --network-policy cilium \
      --enable-acns \
      --only-show-errors \
      --output none; then
    jq -n \
      --arg started_at "$started_at" \
      --arg role "$role" \
      --argjson before "$(jq -s '.' "$before_file")" \
      '{
        schema_version: 1,
        started_at: $started_at,
        success: false,
        repaired: true,
        reason: "aks_reassert_failed",
        failed_role: $role,
        before: $before
      }' >"$OUTPUT_FILE"
    rm -f "$before_file" "$after_file"
    exit 1
  fi
done < <(jq -c 'sort_by(.role)[]' "$CLUSTERS_FILE")
if [ "$drift_detected" = "true" ]; then
  printf '%s\n' "$started_at" >"$repair_marker"
fi

deadline=$(( $(date +%s) + timeout_seconds ))
stable_since=0
last_fingerprint=""
while true; do
  : >"$after_file"
  all_healthy=true
  while IFS= read -r cluster; do
    state=$(capture_cluster_state "$cluster")
    echo "$state" >>"$after_file"
    role=$(jq -r '.role' <<<"$state")
    policy_mode=$(jq -r '.policy_mode' <<<"$state")
    ready=$(jq -r '.cilium.ready' <<<"$state")
    desired=$(jq -r '.cilium.desired' <<<"$state")
    echo "[$role] policy=$policy_mode cilium=$ready/$desired"
    if ! state_is_healthy <<<"$state"; then
      all_healthy=false
    fi
  done < <(jq -c 'sort_by(.role)[]' "$CLUSTERS_FILE")

  now=$(date +%s)
  fingerprint=$(jq -cs \
    'sort_by(.role) | map([
      .role,
      .policy_mode,
      .provisioning_state,
      .cilium.desired,
      .cilium.ready,
      .cilium.updated,
      .cilium.generation,
      .cilium.observed_generation,
      .cilium.config_checksum
    ])' "$after_file")
  if [ "$all_healthy" = "true" ]; then
    if [ "$fingerprint" != "$last_fingerprint" ]; then
      last_fingerprint="$fingerprint"
      stable_since="$now"
    elif [ $((now - stable_since)) -ge "$quiet_seconds" ]; then
      break
    fi
  else
    last_fingerprint=""
    stable_since=0
  fi
  if [ "$now" -ge "$deadline" ]; then
    jq -n \
      --arg started_at "$started_at" \
      --arg observed_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
      --argjson repaired "$repaired" \
      --argjson before "$(jq -s '.' "$before_file")" \
      --argjson after "$(jq -s '.' "$after_file")" \
      '{
        schema_version: 1,
        started_at: $started_at,
        observed_at: $observed_at,
        success: false,
        repaired: $repaired,
        reason: "cilium_policy_did_not_stabilize",
        before: $before,
        after: $after
      }' >"$OUTPUT_FILE"
    rm -f "$before_file" "$after_file"
    exit 1
  fi
  sleep "$poll_seconds"
done

jq -n \
  --arg started_at "$started_at" \
  --arg observed_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --argjson repaired "$repaired" \
  --argjson drift_detected "$drift_detected" \
  --argjson before "$(jq -s '.' "$before_file")" \
  --argjson after "$(jq -s '.' "$after_file")" \
  '{
    schema_version: 1,
    started_at: $started_at,
    observed_at: $observed_at,
    success: true,
    repaired: $repaired,
    drift_detected: $drift_detected,
    before: $before,
    after: $after
  }' >"$OUTPUT_FILE"
rm -f "$before_file" "$after_file"
echo "Cilium policy guard passed for $cluster_count cluster(s); repaired=$repaired drift_detected=$drift_detected"
