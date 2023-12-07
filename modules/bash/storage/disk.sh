#!/bin/bash
source ./modules/bash/utils.sh

set -e

if $DEBUG; then
    set -x
fi

mount_disk_on_remote_vm() {
  local egress_ip_address=$1
  local privatekey_path=$2
  local mount_point=$3

  if [ "$CLOUD" == "azure" ]; then
      local command="sudo parted /dev/sdc --script mklabel gpt mkpart xfspart xfs 0% 100%"
      echo "Run command: $command"
      run_ssh $privatekey_path ubuntu $egress_ip_address "$command"

      local command="sudo mkfs.xfs /dev/sdc1"
      echo "Run command: $command"
      run_ssh $privatekey_path ubuntu $egress_ip_address "$command"

      local command="sudo partprobe /dev/sdc1"
      echo "Run command: $command"
      run_ssh $privatekey_path ubuntu $egress_ip_address "$command"

      local command="sudo mkdir -p $mount_point"
      echo "Run command: $command"
      run_ssh $privatekey_path ubuntu $egress_ip_address "$command"

      local command="sudo mount /dev/sdc1 $mount_point"
      echo "Run command: $command"
      run_ssh $privatekey_path ubuntu $egress_ip_address "$command"

      local command="sudo chmod 777 $mount_point"
      echo "Run command: $command"
      run_ssh $privatekey_path ubuntu $egress_ip_address "$command"
  elif [ "$CLOUD" == "aws" ]; then
      local command="sudo mkfs.ext4 -E nodiscard /dev/nvme1n1"
      echo "Run command: $command"
      run_ssh $privatekey_path ubuntu $egress_ip_address "$command"

      local command="sudo mkdir $mount_point"
      echo "Run command: $command"
      run_ssh $privatekey_path ubuntu $egress_ip_address "$command"

      local command="sudo mount /dev/nvme1n1 $mount_point"
      echo "Run command: $command"
      run_ssh $privatekey_path ubuntu $egress_ip_address "$command"

      local command="sudo chmod 777 $mount_point"
      echo "Run command: $command"
      run_ssh $privatekey_path ubuntu $egress_ip_address "$command"
  else
      echo "Unsupported cloud provider: $CLOUD"
      exit 1
  fi

  local command="df -lh"
  echo "Run command: $command"
  run_ssh $privatekey_path ubuntu $egress_ip_address "$command"
}