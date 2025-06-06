SCENARIO_TYPE=perf-eval
SCENARIO_NAME=k8s-gpu-storage
OWNER=$(whoami)
RUN_ID=$(date +%s)
CLOUD=azure
REGION=eastus2
TERRAFORM_MODULES_DIR=modules/terraform/$CLOUD
TERRAFORM_INPUT_FILE=$(pwd)/scenarios/$SCENARIO_TYPE/$SCENARIO_NAME/terraform-inputs/${CLOUD}.tfvars
SYSTEM_NODE_POOL=${SYSTEM_NODE_POOL:-null}
USER_NODE_POOL=${USER_NODE_POOL:-null}

export ARM_SUBSCRIPTION_ID=$(az account show --query id -o tsv)

az group create --name $RUN_ID --location $REGION \
    --tags "run_id=$RUN_ID" "scenario=${SCENARIO_TYPE}-${SCENARIO_NAME}" "owner=${OWNER}" "creation_date=$(date -u +'%Y-%m-%dT%H:%M:%SZ')" "deletion_due_time=$(date -u -d '+240 hour' +'%Y-%m-%dT%H:%M:%SZ')"

INPUT_JSON=$(jq -n \
  --arg run_id $RUN_ID \
  --arg region $REGION \
  --arg aks_sku_tier "$SKU_TIER" \
  --arg aks_kubernetes_version "$KUBERNETES_VERSION" \
  --arg aks_network_policy "$NETWORK_POLICY" \
  --arg aks_network_dataplane "$NETWORK_DATAPLANE" \
  --arg k8s_machine_type "$K8S_MACHINE_TYPE" \
  --arg k8s_os_disk_type "$K8S_OS_DISK_TYPE" \
  --argjson aks_cli_system_node_pool "$SYSTEM_NODE_POOL" \
  --argjson aks_cli_user_node_pool "$USER_NODE_POOL" \
  '{
    run_id: $run_id,
    region: $region,
    aks_sku_tier: $aks_sku_tier,
    aks_kubernetes_version: $aks_kubernetes_version,
    aks_network_policy: $aks_network_policy,
    aks_network_dataplane: $aks_network_dataplane,
    k8s_machine_type: $k8s_machine_type,
    k8s_os_disk_type: $k8s_os_disk_type,
    aks_cli_system_node_pool: $aks_cli_system_node_pool,
    aks_cli_user_node_pool: $aks_cli_user_node_pool
  }' | jq -c 'with_entries(select(.value != null and .value != ""))')

pushd $TERRAFORM_MODULES_DIR
terraform workspace select -or-create $RUN_ID
terraform init
terraform apply -var json_input=$INPUT_JSON -var-file $TERRAFORM_INPUT_FILE
terraform destroy -var json_input=$INPUT_JSON -var-file $TERRAFORM_INPUT_FILE
terraform workspace select default | terraform workspace list | grep -v "default" | grep -v '*' | xargs -I {} terraform workspace delete -force {}
popd

CLUSTER_NAME=storage-aks
az aks get-credentials --resource-group $RUN_ID --name $CLUSTER_NAME --overwrite-existing
az group delete --name $RUN_ID --yes --no-wait

### ZFS-localpv
helm install zfs-localpv https://openebs.github.io/zfs-localpv/zfs-localpv-2.6.2.tgz -n openebs --create-namespace --skip-crds --set crds.csi.volumeSnapshots.enabled=false

### ACStor
az extension add --upgrade --name k8s-extension

cluster="storage-aks"
rg="1749675064"
nodepools="user"
az aks update -n $cluster -g $rg \
  --enable-azure-container-storage ephemeralDisk --storage-pool-option NVMe \
  --azure-container-storage-nodepools $nodepools

kubectl get diskpool -n acstor # check diskpool
kubectl get sp -n acstor # check storage pool

### ACStor - v2
helm install cert-manager "oci://mcr.microsoft.com/azurelinux/helm/cert-manager" --version 1.12.12-5 \
  --values cert-manager-values.yaml --namespace cert-manager --create-namespace --wait --atomic
kubectl get pods -n cert-manager
# NAME                                      READY   STATUS    RESTARTS   AGE
# cert-manager-67c9d6598f-c6kjk             1/1     Running   0          3m36s
# cert-manager-cainjector-94c787648-jzxrg   1/1     Running   0          3m36s
# cert-manager-webhook-867885787d-lxzwv     1/1     Running   0          3m36s

helm install cns oci://mcr.microsoft.com/cns/cns --version 2.0.0-alpha.nvidia.4 \
  --values cns-values.yaml --namespace cns-system --create-namespace --wait --atomic
kubectl get pods -n cns-system
# NAME                                  READY   STATUS    RESTARTS        AGE
# cns-cluster-manager-89776bb5d-mwtzd   6/6     Running   4 (3m3s ago)    10m
# cns-node-agent-5jmkb                  3/3     Running   2 (3m29s ago)   4m49s
# cns-node-agent-h5kxs                  3/3     Running   4 (2m9s ago)    4m49s
# cns-node-agent-l4mr9                  3/3     Running   2 (3m29s ago)   4m49s

kubectl get storageclass cns-nvmedisk
# NAME           PROVISIONER   RECLAIMPOLICY   VOLUMEBINDINGMODE      ALLOWVOLUMEEXPANSION   AGE
# cns-nvmedisk   lvm.cns.io    Delete          WaitForFirstConsumer   true                   4m1s

kubectl get diskpool -n cns-system
# NAME          STORAGEPOOL   NODE                           CAPACITY       AVAILABLE      USED   RESERVED   PHASE   READY   AGE
# local-c98hr   nvmedisk      aks-user-43000614-vmss000000   960193626112   960193626112   0      0          Bound   True    4m19s
# local-kdhs7   nvmedisk      aks-user-43000614-vmss000001   960193626112   960193626112   0      0          Bound   True    4m19s
# local-lzrw9   nvmedisk      aks-user-43000614-vmss000002   960193626112   960193626112   0      0          Bound   True    2m45s