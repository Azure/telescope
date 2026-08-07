#!/usr/bin/env bash

set -euo pipefail

run_id="${CLUSTERMESH_SMOKE_RUN_ID:?CLUSTERMESH_SMOKE_RUN_ID is required}"
expected_subscription="${CLUSTERMESH_DEBUG_EXPECTED_SUBSCRIPTION_ID:?CLUSTERMESH_DEBUG_EXPECTED_SUBSCRIPTION_ID is required}"
region="${CLUSTERMESH_DEBUG_EXPECTED_REGION:-eastus2euap}"
artifact_dir="${CLUSTERMESH_SMOKE_ARTIFACT_DIR:?CLUSTERMESH_SMOKE_ARTIFACT_DIR is required}"
desired_state_path="${CLUSTERMESH_DEBUG_DESIRED_STATE_PATH:?CLUSTERMESH_DEBUG_DESIRED_STATE_PATH is required}"
private_kube_dir="${AGENT_TEMPDIRECTORY:-/tmp}/n2-reuse-${run_id}-kube"
vm_size="${CLUSTERMESH_SMOKE_VM_SIZE:-Standard_D8_v3}"
kubernetes_version="${CLUSTERMESH_SMOKE_KUBERNETES_VERSION:-1.35}"
fleet_name=clustermesh-flt
profile_name=clustermesh-cmp
vnet_name=clustermesh-shared-vnet
clusters=(clustermesh-1 clustermesh-2)
roles=(mesh-1 mesh-2)
node_subnets=(clustermesh-1-node clustermesh-2-node)
pod_subnets=(clustermesh-1-pod clustermesh-2-pod)
node_prefixes=(10.1.0.0/24 10.2.0.0/24)
pod_prefixes=(10.1.4.0/22 10.2.4.0/22)
result=failed
reason=unexpected_failure

mkdir -p "$artifact_dir"
mkdir -p "$private_kube_dir"
printf '%s\n' "$run_id" > "$artifact_dir/target-run-id.txt"

log() {
  printf '%s %s\n' "$(date -u +%FT%TZ)" "$*" | tee -a "$artifact_dir/preserve.log"
}

wait_for_stable_cluster() {
  local cluster="$1"
  local deadline state stable_reads=0

  deadline=$(( $(date +%s) + 2700 ))
  while [ "$(date +%s)" -lt "$deadline" ]; do
    state=$(az aks show \
      --resource-group "$run_id" \
      --name "$cluster" \
      --query provisioningState \
      -o tsv --only-show-errors 2>/dev/null || echo unknown)
    case "$state" in
      Succeeded)
        stable_reads=$((stable_reads + 1))
        if [ "$stable_reads" -ge 3 ]; then
          log "$cluster sustained Succeeded across 3 checks"
          return 0
        fi
        ;;
      Failed|Canceled)
        reason="aks_terminal_${state,,}"
        echo "$cluster entered terminal provisioningState=$state." >&2
        return 1
        ;;
      *)
        stable_reads=0
        ;;
    esac
    log "$cluster provisioningState=$state stable_reads=$stable_reads/3"
    sleep 20
  done

  reason=aks_stability_timeout
  echo "$cluster did not reach sustained Succeeded within 2700s." >&2
  return 1
}

write_summary() {
  jq -n \
    --arg run_id "$run_id" \
    --arg result "$result" \
    --arg reason "$reason" \
    --arg desired_state_sha "${desired_state_sha:-}" \
    '{
      run_id:$run_id,
      result:$result,
      reason:$reason,
      preserved:true,
      desired_state_sha:$desired_state_sha
    }' \
    > "$artifact_dir/summary.json"
}
cleanup_local() {
  write_summary
  rm -rf "$private_kube_dir"
}
trap cleanup_local EXIT

if ! [[ "$run_id" =~ ^[0-9]+-[0-9a-f]{8}$ ]]; then
  reason=invalid_run_id
  echo "Invalid smoke RUN_ID '$run_id'." >&2
  exit 1
fi
actual_subscription=$(az account show --query id -o tsv)
if [[ "${actual_subscription,,}" != "${expected_subscription,,}" ]]; then
  reason=wrong_subscription
  echo "Expected subscription $expected_subscription, got $actual_subscription." >&2
  exit 1
fi

desired_state_sha=$(sha256sum "$desired_state_path" | awk '{print $1}')
deletion_due_time=$(date -u -d '+24 hours' +%Y-%m-%dT%H:%M:%SZ)

log "create preserved n=2 RG $run_id"
az group create --name "$run_id" --location "$region" \
  --tags "owner=aks" \
         "scenario=perf-eval-clustermesh-scale" \
         "run_id=$run_id" \
         "creation_date=$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
         "deletion_due_time=$deletion_due_time" \
         "SkipAKSCluster=1" \
         "clustermesh_debug_preserved=true" \
         "clustermesh_debug_source_version=${BUILD_SOURCEVERSION:-unknown}" \
         "clustermesh_debug_tfvars_sha256=$desired_state_sha" \
         "clustermesh_debug_expected_clusters=2" \
  --only-show-errors >/dev/null

az network vnet create \
  --resource-group "$run_id" --name "$vnet_name" \
  --location "$region" --address-prefixes 10.0.0.0/8 \
  --only-show-errors >/dev/null

for index in 0 1; do
  az network vnet subnet create \
    --resource-group "$run_id" --vnet-name "$vnet_name" \
    --name "${node_subnets[$index]}" \
    --address-prefixes "${node_prefixes[$index]}" \
    --only-show-errors >/dev/null
  az network vnet subnet create \
    --resource-group "$run_id" --vnet-name "$vnet_name" \
    --name "${pod_subnets[$index]}" \
    --address-prefixes "${pod_prefixes[$index]}" \
    --delegations Microsoft.ContainerService/managedClusters \
    --only-show-errors >/dev/null
done

for index in 0 1; do
  node_subnet_id=$(az network vnet subnet show \
    --resource-group "$run_id" --vnet-name "$vnet_name" \
    --name "${node_subnets[$index]}" --query id -o tsv)
  pod_subnet_id=$(az network vnet subnet show \
    --resource-group "$run_id" --vnet-name "$vnet_name" \
    --name "${pod_subnets[$index]}" --query id -o tsv)
  log "create ${clusters[$index]}"
  timeout --signal=TERM --kill-after=60s 2700s az aks create \
    --resource-group "$run_id" --name "${clusters[$index]}" \
    --location "$region" --kubernetes-version "$kubernetes_version" \
    --tier Standard --nodepool-name default --node-count 2 \
    --node-vm-size "$vm_size" --node-osdisk-type Managed \
    --network-plugin azure --network-dataplane cilium --enable-acns \
    --vnet-subnet-id "$node_subnet_id" --pod-subnet-id "$pod_subnet_id" \
    --service-cidr 192.168.0.0/24 --dns-service-ip 192.168.0.10 \
    --max-pods 110 --enable-managed-identity --generate-ssh-keys \
    --tags "run_id=$run_id" "role=${roles[$index]}" \
           "scenario=perf-eval-clustermesh-scale" "owner=aks" \
    --only-show-errors -o none
done

for cluster in "${clusters[@]}"; do
  wait_for_stable_cluster "$cluster"
done

vnet_id=$(az network vnet show \
  --resource-group "$run_id" --name "$vnet_name" --query id -o tsv)
for index in 0 1; do
  principal_id=$(az aks show \
    --resource-group "$run_id" --name "${clusters[$index]}" \
    --query identity.principalId -o tsv)
  az role assignment create \
    --assignee-object-id "$principal_id" \
    --assignee-principal-type ServicePrincipal \
    --role "Network Contributor" --scope "$vnet_id" \
    --only-show-errors -o none
done

cluster_inventory=$(az resource list \
  --resource-group "$run_id" \
  --resource-type Microsoft.ContainerService/managedClusters \
  --query "[?tags.run_id=='${run_id}' && starts_with(tags.role, 'mesh-')].{role:tags.role,id:id}" \
  -o json)
aks_ids_sha=$(jq -c 'sort_by(.role)' <<< "$cluster_inventory" | sha256sum | awk '{print $1}')
az group update --name "$run_id" \
  --set tags.clustermesh_debug_aks_ids_sha256="$aks_ids_sha" \
  --only-show-errors >/dev/null
printf '%s\n' "$cluster_inventory" | jq 'sort_by(.role)' > "$artifact_dir/aks-ids.json"

log "create healthy Fleet overlay"
az fleet create --resource-group "$run_id" --name "$fleet_name" \
  --location "$region" --output none --only-show-errors
for index in 0 1; do
  cluster_id=$(az aks show \
    --resource-group "$run_id" --name "${clusters[$index]}" \
    --query id -o tsv)
  az fleet member create \
    --resource-group "$run_id" --fleet-name "$fleet_name" \
    --name "${roles[$index]}" --member-cluster-id "$cluster_id" \
    --labels mesh=true --output none --only-show-errors
done
az fleet clustermeshprofile create \
  --resource-group "$run_id" --fleet-name "$fleet_name" \
  --name "$profile_name" --selector mesh=true \
  --output none --only-show-errors
az fleet clustermeshprofile apply \
  --resource-group "$run_id" --fleet-name "$fleet_name" \
  --name "$profile_name" --output none --only-show-errors

for index in 0 1; do
  az aks get-credentials \
    --resource-group "$run_id" --name "${clusters[$index]}" \
    --file "$private_kube_dir/${roles[$index]}.config" \
    --overwrite-existing --only-show-errors >/dev/null
done

deadline=$(( $(date +%s) + 2400 ))
while [ "$(date +%s)" -lt "$deadline" ]; do
  ready=0
  for index in 0 1; do
    kubeconfig="$private_kube_dir/${roles[$index]}.config"
    available=$(KUBECONFIG="$kubeconfig" kubectl -n kube-system \
      get deployment clustermesh-apiserver \
      -o jsonpath='{.status.conditions[?(@.type=="Available")].status}' \
      2>/dev/null || true)
    ip=$(KUBECONFIG="$kubeconfig" kubectl -n kube-system \
      get service clustermesh-apiserver \
      -o jsonpath='{.status.loadBalancer.ingress[0].ip}' \
      2>/dev/null || true)
    peers=$(KUBECONFIG="$kubeconfig" kubectl -n kube-system \
      exec daemonset/cilium -- cilium-dbg status 2>/dev/null \
      | sed -nE 's/.*ClusterMesh:[[:space:]]+([0-9]+)\/[0-9]+ remote clusters ready.*/\1/p' \
      | head -1)
    peers="${peers:-0}"
    log "${roles[$index]} deployment=${available:-missing} LB=${ip:-missing} peers=$peers/1"
    if [ "$available" = "True" ] && [ -n "$ip" ] && [ "$peers" -ge 1 ]; then
      ready=$((ready + 1))
    fi
  done
  if [ "$ready" -eq 2 ]; then
    break
  fi
  sleep 20
done
if [ "${ready:-0}" -ne 2 ]; then
  reason=healthy_mesh_did_not_converge
  exit 1
fi

az fleet clustermeshprofile list-members \
  --resource-group "$run_id" --fleet-name "$fleet_name" \
  --name "$profile_name" -o json > "$artifact_dir/profile-members.json"

reason=intentional_failure_after_healthy_mesh
log "intentional failure injected; RG remains preserved for reset/resume smoke"
exit 42
