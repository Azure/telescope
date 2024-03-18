#!/bin/bash

# Description:
#   This function is used to create a VM in GCP.
#
# Parameters:
#   - $1: The name of the VM (e.g. my-vm)
#   - $2: The size of the VM (e.g. c3-highcpu-4)
#   - $3: The OS identifier the VM will use (e.g. projects/ubuntu-os-cloud/global/images/ubuntu-2004-focal-v20240229)
#   - $4: The region where the VM will be created (e.g. us-east1)
#   - $5: [optional] The accelerator to use (e.g. count=8,type=nvidia-h100-80gb, default value is empty)
#   - $6: [optional] The labels to use (e.g. "owner=azure_devops,creation_time=2024-03-11T19:12:01Z", default value is empty)
#
# Notes:
#   - the VM name is returned if no errors occurred
#
# Usage: create_vm <vm_name> <vm_size> <vm_os> <region> [accelerator] [labels]
create_vm() {
    local vm_name=$1
    local vm_size=$2
    local vm_os=$3
    local region=$4
    local accelerator="${5:-""}"
    local labels="${6:-""}"

    if gcloud compute instances create "$vm_name" --zone "$region" --machine-type "$vm_size" --image "$vm_os" --accelerator "$accelerator" --labels=$labels --quiet; then
        echo "$vm_name"
    fi
}

# Description:
#   This function is used to delete a VM in GCP.
#
# Parameters:
#   - $1: The name of the VM (e.g. c3-highcpu-4)
#   - $2: The region under which the VM was created (e.g. us-east1)
#
# Notes:
#   - the VM name is returned if no errors occurred
#
# Usage: delete_vm <vm_name> <region>
delete_vm() {
    local vm_name=$1
    local region=$2

    if gcloud compute instances delete "$vm_name" --zone "$region" --quiet; then
        echo "$vm_name"
    fi
}
