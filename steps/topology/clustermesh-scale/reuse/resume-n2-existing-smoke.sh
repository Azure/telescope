#!/usr/bin/env bash

set -euo pipefail

target_run_id="${CLUSTERMESH_DEBUG_TARGET_RUN_ID:?CLUSTERMESH_DEBUG_TARGET_RUN_ID is required}"
confirm="${CLUSTERMESH_DEBUG_CONFIRM_RESUME:?CLUSTERMESH_DEBUG_CONFIRM_RESUME is required}"
expected_subscription="${CLUSTERMESH_DEBUG_EXPECTED_SUBSCRIPTION_ID:?CLUSTERMESH_DEBUG_EXPECTED_SUBSCRIPTION_ID is required}"
region="${CLUSTERMESH_DEBUG_EXPECTED_REGION:-eastus2euap}"
artifact_dir="${CLUSTERMESH_SMOKE_ARTIFACT_DIR:?CLUSTERMESH_SMOKE_ARTIFACT_DIR is required}"
desired_state_path="${CLUSTERMESH_DEBUG_DESIRED_STATE_PATH:?CLUSTERMESH_DEBUG_DESIRED_STATE_PATH is required}"
repository_root="${REPOSITORY_ROOT:-$(cd "$(dirname "$0")/../../../.." && pwd)}"
private_kube_dir="${AGENT_TEMPDIRECTORY:-/tmp}/n2-reuse-${target_run_id}-existing"
workload_namespace="persistence-workload-smoke"

if [ "$confirm" != "$target_run_id" ]; then
  echo "Resume confirmation mismatch." >&2
  exit 1
fi

actual_subscription=$(az account show --query id -o tsv)
if [[ "${actual_subscription,,}" != "${expected_subscription,,}" ]]; then
  echo "Expected subscription $expected_subscription, got $actual_subscription." >&2
  exit 1
fi

mkdir -p "$artifact_dir" "$private_kube_dir"
cleanup_local() {
  local kubeconfig
  for kubeconfig in "$private_kube_dir"/*.config; do
    [ -f "$kubeconfig" ] || continue
    KUBECONFIG="$kubeconfig" kubectl delete namespace "$workload_namespace" \
      --ignore-not-found --wait=false >/dev/null 2>&1 || true
  done
  rm -rf "$private_kube_dir"
}
trap cleanup_local EXIT

export CLUSTERMESH_DEBUG_EXPECTED_CLUSTER_COUNT=2
export CLUSTERMESH_DEBUG_EXPECTED_TFVARS_SHA256
if [ -z "${CLUSTERMESH_DEBUG_EXPECTED_TFVARS_SHA256:-}" ]; then
  CLUSTERMESH_DEBUG_EXPECTED_TFVARS_SHA256=$(sha256sum "$desired_state_path" | awk '{print $1}')
fi
export CLUSTERMESH_DEBUG_EXTEND_LEASE_HOURS=24
export CLUSTERMESH_DEBUG_REQUIRE_OVERLAY_RESET=false
export CLUSTERMESH_DEBUG_MANIFEST_PATH="$artifact_dir/validation.json"

bash "$repository_root/steps/topology/clustermesh-scale/reuse/validate-existing-scale.sh"

expected_ids_sha=$(az group show --name "$target_run_id" \
  --query tags.clustermesh_debug_aks_ids_sha256 -o tsv)
clusters=$(az resource list \
  --resource-group "$target_run_id" \
  --resource-type Microsoft.ContainerService/managedClusters \
  --query "[?tags.run_id=='${target_run_id}' && starts_with(tags.role, 'mesh-')].{name:name,rg:resourceGroup,role:tags.role,id:id}" \
  -o json)
current_ids_sha=$(jq -c '[.[] | {id,role}] | sort_by(.role)' <<<"$clusters" |
  sha256sum | awk '{print $1}')
if [ "$current_ids_sha" != "$expected_ids_sha" ]; then
  echo "AKS resource IDs changed before existing-Fleet resume." >&2
  exit 1
fi

if ! az fleet show --resource-group "$target_run_id" \
    --name clustermesh-flt --only-show-errors >/dev/null; then
  echo "Expected preserved Fleet clustermesh-flt to exist." >&2
  exit 1
fi

members=$(az fleet member list \
  --resource-group "$target_run_id" \
  --fleet-name clustermesh-flt \
  -o json --only-show-errors)
if ! jq -e -n \
    --argjson members "$members" \
    --argjson clusters "$clusters" '
      ($clusters
        | map({key:.role, value:(.id | ascii_downcase)})
        | from_entries) as $expected
      | ($members
        | map({key:.name, value:(.clusterResourceId | ascii_downcase)})
        | from_entries) as $actual
      | ($members | length) == 2
        and $actual == $expected
    ' >/dev/null; then
  echo "Preserved Fleet member inventory no longer matches the original AKS clusters." >&2
  exit 1
fi

profile_members=$(az fleet clustermeshprofile list-members \
  --resource-group "$target_run_id" \
  --fleet-name clustermesh-flt \
  --name clustermesh-cmp \
  -o json --only-show-errors)
printf '%s\n' "$profile_members" > "$artifact_dir/profile-members.json"
connected=$(jq '[.[] | select(.meshProperties.status.state=="Connected")] | length' \
  <<<"$profile_members")
if [ "$connected" -ne 2 ]; then
  echo "Expected preserved Fleet to remain 2/2 Connected, found $connected." >&2
  exit 1
fi

printf '[]\n' > "$artifact_dir/workload-evidence.json"
for row in $(jq -c '.[]' <<<"$clusters"); do
  name=$(jq -r '.name' <<<"$row")
  role=$(jq -r '.role' <<<"$row")
  kubeconfig="$private_kube_dir/$role.config"
  az aks get-credentials \
    --resource-group "$target_run_id" \
    --name "$name" \
    --file "$kubeconfig" \
    --overwrite-existing --only-show-errors >/dev/null
  available=$(KUBECONFIG="$kubeconfig" kubectl -n kube-system get \
    deployment clustermesh-apiserver \
    -o jsonpath='{.status.conditions[?(@.type=="Available")].status}')
  lb_ip=$(KUBECONFIG="$kubeconfig" kubectl -n kube-system get \
    service clustermesh-apiserver \
    -o jsonpath='{.status.loadBalancer.ingress[0].ip}')
  peers=$(KUBECONFIG="$kubeconfig" kubectl -n kube-system exec ds/cilium -- \
    cilium-dbg status 2>&1 |
    sed -nE 's/.*ClusterMesh:[[:space:]]+([0-9]+)\/[0-9]+ remote clusters ready.*/\1/p' |
    head -1)
  if [ "$available" != "True" ] || [ -z "$lb_ip" ] || [ "${peers:-0}" -lt 1 ]; then
    echo "$role existing Fleet is not functionally healthy: deployment=$available lb=${lb_ip:-missing} peers=${peers:-0}/1" >&2
    exit 1
  fi

  KUBECONFIG="$kubeconfig" kubectl create namespace "$workload_namespace"
  KUBECONFIG="$kubeconfig" kubectl -n "$workload_namespace" apply -f - <<'YAML'
apiVersion: apps/v1
kind: Deployment
metadata:
  name: persistence-smoke
spec:
  replicas: 1
  selector:
    matchLabels:
      app: persistence-smoke
  template:
    metadata:
      labels:
        app: persistence-smoke
    spec:
      containers:
        - name: pause
          image: mcr.microsoft.com/oss/kubernetes/pause:3.9
YAML
  KUBECONFIG="$kubeconfig" kubectl -n "$workload_namespace" rollout status \
    deployment/persistence-smoke --timeout=300s
  KUBECONFIG="$kubeconfig" kubectl -n "$workload_namespace" scale \
    deployment/persistence-smoke --replicas=3
  KUBECONFIG="$kubeconfig" kubectl -n "$workload_namespace" rollout status \
    deployment/persistence-smoke --timeout=300s

  pods=$(KUBECONFIG="$kubeconfig" kubectl -n "$workload_namespace" get pods \
    -l app=persistence-smoke -o json)
  ready_pods=$(jq '
    [
      .items[]
      | select(
          .status.phase == "Running"
          and (.status.podIP // "") != ""
          and (.status.containerStatuses | length) > 0
          and all(.status.containerStatuses[]; .ready == true)
        )
    ]
    | length
  ' <<<"$pods")
  if [ "$ready_pods" -ne 3 ]; then
    echo "$role workload smoke expected 3 Ready networked pods, found $ready_pods." >&2
    exit 1
  fi

  evidence_tmp=$(mktemp "$artifact_dir/workload-evidence.tmp.XXXXXX")
  jq \
    --arg role "$role" \
    --arg cluster "$name" \
    --argjson pods "$pods" \
    '. += [{
      role: $role,
      cluster: $cluster,
      replicas: 3,
      pod_ips: [$pods.items[].status.podIP]
    }]' \
    "$artifact_dir/workload-evidence.json" > "$evidence_tmp"
  mv -f "$evidence_tmp" "$artifact_dir/workload-evidence.json"

  KUBECONFIG="$kubeconfig" kubectl delete namespace "$workload_namespace" \
    --wait=false
  delete_deadline=$(( $(date +%s) + 300 ))
  while [ "$(date +%s)" -lt "$delete_deadline" ]; do
    if ! KUBECONFIG="$kubeconfig" kubectl get namespace "$workload_namespace" \
        >/dev/null 2>&1; then
      break
    fi
    sleep 5
  done
  if KUBECONFIG="$kubeconfig" kubectl get namespace "$workload_namespace" \
      >/dev/null 2>&1; then
    echo "$role workload namespace did not delete within 300s." >&2
    exit 1
  fi
done

jq -n \
  --arg run_id "$target_run_id" \
  '{
    run_id:$run_id,
    result:"passed",
    aks_ids_preserved:true,
    existing_fleet_preserved:true,
    connected_members:2,
    workload_smoke:true,
    workload_clusters:2,
    workload_replicas_per_cluster:3
  }' > "$artifact_dir/summary.json"
echo "Existing-Fleet n=2 resume passed with unchanged AKS IDs, 2/2 connectivity, and persisted-cluster workloads."
