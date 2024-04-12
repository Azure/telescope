#!/bin/bash

#Description
#   This script contains the functions to manage the resources in the resource group.
#
# Parameters:
#  - $1:  run_id: the ID of the test run (e.g. c23f34-vf34g34g-3f34gf3gf4-fd43rf3f43)
# 
# Returns: name of the VM instance
# Usage: get_vm_instance_by_name <run_id>
get_vm_instance_by_name() {
    local run_id=$1

    echo "$(aws ec2 describe-instances --filters "Name=tag:run_id,Values=$run_id" --query "Reservations[].Instances[].Tags[?Key=='Name'].Value" --output text)"
}

#Description
#   This function gets the disk instances by name.
#
# Parameters:
#  - $1:  run_id: the ID of the test run (e.g. c23f34-vf34g34g-3f34gf3gf4-fd43rf3f43)
#
# Returns: name of the disk instances
# Usage: get_disk_instances_by_name <run_id>
get_disk_instances_by_name() {
    local run_id=$1
    
    echo "$(aws ec2 describe-volumes --filters "Name=tag:run_id,Values=$run_id" --query "Volumes[].Tags[?Key=='Name'].Value" --output text)"
}

#Description
#   This function attaches a disk to a VM.
#
# Parameters:
#  - $1:  vm_name: the name of the VM instance (e.g. vm-1)
#  - $2:  disk_name: the name of the disk instance (e.g. disk-1)
#  - $3:  resource_group: the name of the resource group (e.g. c23f34-vf34g34g-3f34gf3gf4-fd43rf3f43)
#
# Returns: Error message of the operation otherwise nothing
# Usage: attach_disk <vm_name> <disk_name> <resource_group>
attach() {
    local vm_name=$1
    local disk_name=$2
    local resource_group=$3

    echo "$(aws ec2 attach-volume --volume-id $disk_name --instance-id $vm_name --device /dev/sdf)"
}

#Description
#   This function detaches a disk from a VM.
#
# Parameters:
#  - $1:  vm_name: the name of the VM instance (e.g. vm-1)
#  - $2:  disk_name: the name of the disk instance (e.g. disk-1)
#  - $3:  resource_group: the name of the resource group (e.g. c23f34-vf34g34g-3f34gf3gf4-fd43rf3f43)
#
# Returns: Error message of the operation otherwise nothing
# Usage: detach_disk <vm_name> <disk_name> <resource_group>
detach() {
    local vm_name=$1
    local disk_name=$2
    local resource_group=$3

    echo "$(aws ec2 detach-volume --volume-id $disk_name)"
}

#Description
#   This function validates the resources in the resource group.
#
# Parameters:
#  = $1:  run_id: the ID of the test run (e.g. c23f34-vf34g34g-3f34gf3gf4-fd43rf3f43)
#
# Returns: None
# Usage: validate_resources <run_id>
validate_resources() {
    local run_id=$1
    
    # Retrieve VMs from the resource group
    vm_count=$(aws ec2 describe-instances --filters "Name=tag:run_id,Values=$run_id" --query "Reservations[].Instances[].InstanceId" --output text | wc -l)

    # Check if there is only one VM
    if [ $vm_count -ne 1 ]; then
        echo "Error: There should be exactly one VM in the resource group."
        exit 1
    fi

    # Retrieve disks from the resource group
    disk_count=$(aws ec2 describe-volumes --filters "Name=tag:run_id,Values=$run_id" --query "Volumes[].VolumeId" --output text | wc -l)

    # Check if there is at least one disk
    if [ $disk_count -lt 1 ]; then
        echo "Error: There should be at least one disk in the resource group."
        exit 1
    fi
}

#Description
#   This function gets the storage type and size of a disk.
#
# Parameters:
#  - $1:  disk_name: the name of the disk instance (e.g. disk-1)
#
# Returns: JSON object containing the storage type and size of the disk
# Usage: get_disk_storage_type_and_size <disk_name>
get_disk_storage_type_and_size() {
    local disk_name=$1

    echo "$(aws ec2 describe-volumes --volume-ids $disk_name --query "Volumes[].{StorageType:VolumeType, Size:Size}" --output json)"
}

# Function: get_disk_attached_state
#
# Description:
#   This function checks the attached state of a disk in Aws.
#
# Parameters:
#   - disk_name: The name of the disk to check.
#   - resource_group: The resource group where the disk is located.
#
# Returns:
#   - true if the disk is attached, false otherwise.
#
get_disk_attached_state() {
    local disk_name=$1
    local resource_group=$2
    [ "$(aws ec2 describe-volumes --volume-ids $disk_name --query "Volumes[].Attachments[].State" --output text)" == "attached" ]
}

#Description
#   This function gets the operating system and size of a VM.
#
# Parameters:
#  - $1:  vm_name: the name of the VM instance (e.g. vm-1)
#  - $2:  resource_group: the name of the resource group (e.g. c23f34-vf34g34g-3f34gf3gf4-fd43rf3f43)
#
# Returns: JSON object containing the operating system and size of the VM
# Usage: get_vm_properties <vm_name> <resource_group>
get_vm_properties() {
    local vm_name=$1

    echo "$(aws ec2 describe-instances --instance-ids $vm_name --query "Reservations[].Instances[].{OperatingSystem:Platform, Size:InstanceType}" --output json)"
}

#Description
#   This function gets the region of a resource group.
#
# Parameters:
#  - $1:  resource_group: the name of the resource group (e.g. c23f34-vf34g34g-3f34gf3gf4-fd43rf3f43)
#
# Returns: The region of the resource group
# Usage: get_region <resource_group>
get_region() {
    local run_id=$1
        
    echo "$(aws ec2 describe-instances --filters "Name=tag:run_id,Values=$run_id" --query "Reservations[].Instances[].Placement.AvailabilityZone" --output text)"
}
