#!/bin/bash
source ./modules/bash/utils.sh

azure_storage_create_fileshare() {
  local resource_group=$1
  local storage_account_name=$2
  local storage_share_name=$3
  local storage_share_quota=$4
  local storage_share_protocol=$5

  extra_args=""
  # if storage_share_quota is set
  if [ ! -z "$storage_share_quota" ]; then
    extra_args="$extra_args --quota $storage_share_quota"
  fi
  # if storage_share_protocol is set
  if [ ! -z "$storage_share_protocol" ]; then
    extra_args="$extra_args --enabled-protocols $storage_share_protocol"
  fi

  az storage share-rm create \
    --resource-group $resource_group \
    --storage-account $storage_account_name \
    --name $storage_share_name \
    $extra_args
}

azure_get_subnet_id() {
  local resource_group=$1
  local vnet_name=$2
  local subnet_name=$3

  subnet_id=$(az network vnet subnet show \
    --resource-group $resource_group \
    --vnet-name $vnet_name \
    --name $subnet_name \
    --query id --output tsv)
  echo $subnet_id
}

azure_add_network_rule_to_storage_account() {
  local resource_group=$1
  local storage_account_name=$2
  local subnet_id=$3

  # default action is to deny all network access
  az storage account update \
    --resource-group $resource_group \
    --name $storage_account_name \
    --default-action Deny

  az storage account network-rule add \
    --resource-group $resource_group \
    --account-name $storage_account_name \
    --subnet $subnet_id
  sleep 60
}

azure_get_storage_http_endpoint() {
  local resource_group=$1
  local storage_account_name=$2

  HTTP_ENDPOINT=$(az storage account show \
      --resource-group $resource_group \
      --name $storage_account_name \
      --query "primaryEndpoints.file" --output tsv | tr -d '"')
  echo $HTTP_ENDPOINT
}

mount_azure_storage_fileshare_on_remote_vm() {
  local egress_ip_address=$1
  local privatekey_path=$2

  local storage_account_name=$3
  local storage_account_key=$4
  local storage_account_http_endpoint=$5
  local storage_share_name=$6
  local mount_point=$7
  local protocol=$8

  if $DEBUG; then
    echo "privatekey:"
    cat $privatekey_path
  fi

  local mount_cmd=""
  # if protocol is SMB, we will mount it with cifs
  # if protocol is NFS, we will mount it with nfs
  if [ "${protocol}" == "SMB" ]; then
    smb_path=$(echo ${storage_account_http_endpoint} | cut -c7-${#storage_account_http_endpoint})${storage_share_name}
    mount_cmd="sudo mount -t cifs ${smb_path} ${mount_point} -o username=${storage_account_name},password=${storage_account_key},serverino,nosharesock,actimeo=30,mfsymlinks"
  elif [ "${protocol}" == "NFS" ]; then
    mount_cmd="sudo mount -t nfs ${storage_account_name}.file.core.windows.net:/${storage_account_name}/${storage_share_name} ${mount_point} -o vers=4,minorversion=1,sec=sys,nconnect=4"
  else
    echo "Protocol ${protocol} is not supported"
    exit 1
  fi

  local cmds=(
    "sudo mkdir ${mount_point} -p"
    "$mount_cmd"
    "sleep 5"
    "sudo df -lh & sudo mount"
  )

  for cmd in "${cmds[@]}"; do
    echo "Running: $cmd"
    run_ssh $privatekey_path ubuntu $egress_ip_address 2222 "$cmd"
  done
}

run_small_file_perf_on_remote_vm() {
  local egress_ip_address=$1
  local privatekey_path=$2
  local mount_point=$3
  local result_dir=$4

  mkdir -p $result_dir

  local command="sudo df -hT $mount_point & sudo mount"
  run_ssh $privatekey_path ubuntu $egress_ip_address 2222 "$command"

  echo "Getting small file"

  set +x # disable debug output because it will mess up the output of fio
  local command="((time -p ( wget -qO- https://wordpress.org/latest.tar.gz | tar xvz -C $mount_point )) 2>&1)"
  echo "Run command: $command"
  run_ssh $privatekey_path ubuntu $egress_ip_address 2222 "$command" | tee $result_dir/worldpress.log

  if $DEBUG; then # re-enable debug output if DEBUG is set
    set -x
  fi
}