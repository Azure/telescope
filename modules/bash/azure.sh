#!/bin/bash

azure_blob_upload() {
  local source_file_name=$1
  local destination_file_name=$2
  local subfolder=$3
  local account_name=$4
  local account_key=$5
  local container_name=$6

  az storage blob upload \
    --file $source_file_name \
    --name ${subfolder}/${destination_file_name} \
    --account-name $account_name \
    --account-key $account_key \
    --container-name $container_name
}

azure_vm_ip_address() {
  local resource_group=$1
  local vm_name=$2
  local ip_type=$3

  if [ "$ip_type" == "public" ]; then
    ip_address=$(az vm list-ip-addresses -g $resource_group -n $vm_name --query '[].virtualMachine.network.publicIpAddresses[0].ipAddress' -o tsv)
  elif [ "$ip_type" == "private" ]; then
    ip_address=$(az vm list-ip-addresses  -g $resource_group -n $vm_name --query [].virtualMachine.network.privateIpAddresses[0] -o tsv)
  else
    ip_address="invalid ip type $ip_type"
  fi
  
  echo $ip_address
}

azure_public_ip_address() {
  local resource_group=$1
  local ip_name=$2

  ip_address=$(az network public-ip show -g $resource_group -n $ip_name --query ipAddress -o tsv)
  echo $ip_address
}

azure_vm_run_command() {
  local resource_group=$1
  local vm_name=$2
  local script=$3
  local parameters=$4

  if [ -n "$parameters" ]; then
    parameter_option="--parameters $parameters"
  fi
  az vm run-command invoke -g $resource_group -n $vm_name --command-id RunShellScript --scripts "$script" $parameter_option
}

azure_vmss_run_command() {
  local resource_group=$1
  local vmss_name=$2
  local script=$3
  local parameters=$4

  if [ -n "$parameters" ]; then
    parameter_option="--parameters $parameters"
  fi
  az vmss list-instances -g $resource_group -n $vmss_name --query "[].id" --output tsv | \
  az vmss run-command invoke -g $resource_group -n $vmss_name --ids @- --command-id RunShellScript --scripts "$script" $parameter_option
}

azure_get_vm_info() {
  local resource_group=$1
  local vm_name=$2

  res=$(az vm show --resource-group $resource_group --name $vm_name --query "{id:id, vmId:vmId}" --output json)
  echo $res
}

azure_get_1st_storage_account_name_by_rg() {
  local resource_group=$1

  resource_group_names=$(az group list --query "[?contains(name, '$resource_group')].name" -o tsv)

  for resource_group_name in $resource_group_names; do
    storage_account_name=$(az storage account list -g $resource_group_name --query "[].name" -o tsv | head -n 1)
    if [ -n "$storage_account_name" ]; then
      break
    fi
  done
  echo $storage_account_name
}

azure_aks_start_nginx()
{
  local resource_group=$1
  local aksName=$2
  local scenario_type=$3
  local scenario_name=$4

  az aks get-credentials -n $aksName -g $resource_group
  subnet_name=$(kubectl get nodes -o json | jq -r '.items[0].metadata.labels."kubernetes.azure.com/network-subnet"')
  
  local file_source=./scenarios/${scenario_type}/${scenario_name}/bash-scripts
  kubectl apply -f "${file_source}/nginxCert.yml"
  kubectl apply -f "${file_source}/aksSetup.yml"


  helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx
  helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
  helm repo update
  helm upgrade --install prometheus prometheus-community/prometheus
  helm upgrade --install ingress-nginx ingress-nginx/ingress-nginx \
    --namespace ingress-nginx \
    --set controller.service.externalTrafficPolicy=Local \
    --set controller.service.ports.https=443 \
    --set controller.replicaCount=3 \
    --set controller.service.loadBalancerIP=10.10.1.250 \
    --set controller.service.annotations."service\.beta\.kubernetes\.io/azure-load-balancer-internal"=true \
    --set controller.service.annotations."service\.beta\.kubernetes\.io/azure-load-balancer-internal-subnet"="${subnet_name}" \
    --set controller.extraArgs.default-ssl-certificate="ingress-nginx/ingress-tls" \
    --set controller.admissionWebhooks.enabled=false \
    --wait-for-jobs
}

azure_aks_deploy_fio()
{
  local resource_group=$1
  local aksName=$2
  local scenario_type=$3
  local scenario_name=$4
  local disk_type=$5
  local disk_size_in_gb=$6
  local replica_count=$7
  local data_disk_iops_read_write=$8
  local data_disk_mbps_read_write=$9

  az aks get-credentials -n $aksName -g $resource_group
  local file_source=./scenarios/${scenario_type}/${scenario_name}/yml-files/azure

  if [ -z "$data_disk_iops_read_write" ]; then
    sed -i "s/\(skuName: \).*/\1$disk_type/" "${file_source}/storage-class.yml"
    kubectl apply -f "${file_source}/storage-class.yml"
  else
    sed -i "s/\(skuName: \).*/\1$disk_type/" "${file_source}/storage-class-provisioned.yml"
    sed -i "s/\(DiskIOPSReadWrite: \).*/\1\"$data_disk_iops_read_write\"/" "${file_source}/storage-class-provisioned.yml"
    sed -i "s/\(DiskMBpsReadWrite: \).*/\1\"$data_disk_mbps_read_write\"/" "${file_source}/storage-class-provisioned.yml"
    kubectl apply -f "${file_source}/storage-class-provisioned.yml"
  fi

  sed -i "s/\(storage: \).*/\1${disk_size_in_gb}Gi/" "${file_source}/pvc.yml"
  sed -i "s/\(replicas: \).*/\1$replica_count/" "${file_source}/fio.yml"
  
  kubectl apply -f "${file_source}/pvc.yml"
  kubectl apply -f "${file_source}/fio.yml"
}

azure_aks_deploy_fio_fileshare()
{
  local resource_group=$1
  local aksName=$2
  local scenario_type=$3
  local scenario_name=$4
  local protocol=$(echo $5 | tr '[:upper:]' '[:lower:]') # convert to lowercase
  local share_size_in_gb=$6
  local replica_count=$7

  az aks get-credentials -n $aksName -g $resource_group
  local file_source=./scenarios/${scenario_type}/${scenario_name}/yml-files/azure

  if [ $protocol = "smb" ]; then
    kubectl apply -f "${file_source}/storage-class-smb.yml"
  else
    kubectl apply -f "${file_source}/storage-class-nfs.yml"
  fi

  sed -i "s/\(storage: \).*/\1${share_size_in_gb}Gi/" "${file_source}/pvc.yml"
  sed -i "s/\(replicas: \).*/\1$replica_count/" "${file_source}/fio.yml"
  
  kubectl apply -f "${file_source}/pvc.yml"
  kubectl apply -f "${file_source}/fio.yml"
}

azure_create_vnet_peering()
{
  local run_id=$1
    # Step 1: Find all VNets in the specified resource group
    vnets=$(az network vnet list --resource-group $run_id --query '[].name' -o tsv)

    # Step 2: Create VNet peering between each pair of VNets
    for vnet1 in $vnets; do
        for vnet2 in $vnets; do
            if [[ "$vnet1" != "$vnet2" ]]; then
                az network vnet peering create \
                    --name "${vnet1}-to-${vnet2}" \
                    --resource-group $run_id \
                    --vnet-name $vnet1 \
                    --remote-vnet $vnet2 \
                    --allow-vnet-access
            fi
        done
    done
}