#!/bin/bash
source ./modules/bash/utils.sh

azure_get_1st_storage_account_name_by_prefix() {
  local resource_group=$1
  local storage_account_name_prefix=$2

  storage_account_name=$(az storage account list -g $resource_group --query "[?starts_with(name, '$storage_account_name_prefix')].name" -o tsv | head -n 1)
  echo $storage_account_name
}

azure_get_storage_account_key() {
  local resource_group=$1
  local storage_account_name=$2

  storage_account_key=$(az storage account keys list -g $resource_group -n $storage_account_name --query '[0].value' -o tsv)
  echo $storage_account_key
}

azure_create_storage_container() {
  local storage_account_name=$1
  local storage_account_key=$2
  local container_name=$3

  az storage container create \
    --account-name $storage_account_name \
    --account-key $storage_account_key \
    --name $container_name
}

# usage example:
# azure_mount_azure_storage_accont_container_on_remote_vm $egress_ip_address $privatekey_path $storage_account_name $storage_account_key $container_name $mount_point
mount_azure_storage_accont_container_on_remote_vm() {
  local egress_ip_address=$1
  local privatekey_path=$2

  local storage_account_name=$3
  local storage_account_key=$4
  local container_name=$5
  local mount_point=$6

  # we will create a ramdisk (/mnt/ramdisk/blobfuse2tmp) and mount azure blob on it
  local cmds=(
    "sudo mkdir /mnt/ramdisk"
    "sudo mount -t tmpfs -o size=16g tmpfs /mnt/ramdisk"
    "sudo mkdir /mnt/ramdisk/blobfuse2tmp"
    "sudo chown ubuntu /mnt/ramdisk/blobfuse2tmp"
    "sudo mkdir ${mount_point} -p"
    "sudo AZURE_STORAGE_ACCOUNT=${storage_account_name} AZURE_STORAGE_ACCESS_KEY=${storage_account_key} blobfuse2 mount ${mount_point} --container-name=${container_name} --tmp-path=/mnt/ramdisk/blobfuse2tmp"
    "sudo df -lh"
  )

  for cmd in "${cmds[@]}"; do
    echo "Running: $cmd"
    run_ssh $privatekey_path ubuntu $egress_ip_address 2222 "$cmd"
  done
}

mount_s3_bucket_on_remote_vm() {
  local egress_ip_address=$1
  local privatekey_path=$2

  local aws_access_key_id=$3
  local aws_secret_access_key=$4

  local bucket_name=$5
  local mount_point=$6

  echo $aws_access_key_id:$aws_secret_access_key > /tmp/passwd-s3fs
  run_scp_remote $privatekey_path ubuntu $egress_ip_address 2222 /tmp/passwd-s3fs /tmp/passwd-s3fs

  # notice: please assign AmazonS3FullAccess policy to the IAM user to make this work
  echo "current aws access key id: $aws_access_key_id"
  local cmds=(
    "sudo chown root:root /tmp/passwd-s3fs"
    "sudo chmod 600 /tmp/passwd-s3fs"
    "sudo mkdir ${mount_point} -p"
    "sudo s3fs ${bucket_name} ${mount_point} -o passwd_file=/tmp/passwd-s3fs -o url=https://s3.us-east-2.amazonaws.com"
    "sudo sleep 2 # wait for mount to be ready"
    "sudo df -lh"
  )

  for cmd in "${cmds[@]}"; do
    echo "Running: $cmd"
    run_ssh $privatekey_path ubuntu $egress_ip_address 2222 "$cmd"
  done

  check_mount_point $egress_ip_address $privatekey_path $mount_point s3fs
}

check_mount_point() {
  local ip_address=$1
  local privatekey_path=$2

  local mount_point=$3
  local expected_fs=$4

  echo "Check mount point"
  max_retries=10
  i=0
  status=1
  while true
  do
    echo "run_ssh $privatekey_path ubuntu $ip_address sudo df -hT $mount_point"
    run_ssh $privatekey_path ubuntu $ip_address 2222 "sudo df -hT $mount_point" | grep $expected_fs
    status=$?
    i=$((i+1))

    if [ "$status" -eq 0 ]; then
      break
    elif [ "$i" -eq "$max_retries" ]; then
      echo "not find mount point with expected fs after $max_retries retries, check df & syslog for more details"
      run_ssh $privatekey_path ubuntu $ip_address 2222 "sudo df -hT $mount_point"
      run_ssh $privatekey_path ubuntu $ip_address 2222 "sudo tail -n 50 /var/log/syslog"
      exit 1
    fi

    sleep 30
  done
}