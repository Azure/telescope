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

    echo "$(aws ec2 describe-instances --filters "Name=tag:run_id,Values=$run_id" --query "Reservations[].Instances[].InstanceId" --output text)"
}

# Description:
#   This function retrieves the disk instances by name that are available in the specified region.
#
# Parameters:
#  - $1: run_id: the ID of the test run (e.g. c23f34-vf34g34g-3f34gf3gf4-fd43rf3f43)
#  - $2: region: the region where the disk instances are located
#
# Returns: The names of the available disk instances
# Usage: get_available_disk_instances <run_id> <region>
get_available_disk_instances() {
    local run_id=$1
    local region=$2
    
    echo "$(aws ec2 describe-volumes \
    --filters Name=status,Values=available Name=availability-zone,Values=$region \
    --query "Volumes[*].VolumeId" \
    --output text)"
}


# Description:
#   This function attaches or detaches a disk to/from a vm based on the operation parameter.
#
# Parameters:
#  - $1: operation: the operation to perform (attach or detach)
#  - $2: vm_name: the name of the VM instance (e.g. vm-1)
#  - $3: disk_name: the name of the disk instance (e.g. disk-1)
#  - $4: run_id: the name of the resource group (e.g. c23f34-vf34g34g-3f34gf3gf4-fd43rf3f43)
#
# Returns: Error message of the operation otherwise nothing
# Usage: attach_or_detach_disk <operation> <vm_name> <disk_name> <run_id>
attach_or_detach_disk() {
    local operation=$1
    local vm_name=$2
    local disk_name=$3
    local run_id=$4
    #TODO: wait until disk is attached
    start_time=$(date +%s)
    if [ "$operation" == "attach" ]; then
        local output_message="$(aws ec2 attach-volume --volume-id $disk_name --instance-id $vm_name --device /dev/sdf)"
    elif [ "$operation" == "detach" ]; then
        local output_message="$(aws ec2 detach-volume --volume-id $disk_name)"
    else
        echo "Invalid operation. Please specify either 'attach' or 'detach'."
        exit 1
    fi
    end_time=$(date +%s)

    (
        set -Ee

        _catch() {
            echo '{"succeeded": "false", "execution_time": "null", "unit": "seconds", "data": {"error": "Unknown error"}}'
        }
        trap _catch ERR

        if [[ "$output_message" == "ERROR: "* ]]; then
            local succeeded="false"
            local execution_time=-1
            local data=$(jq -n -r -c --arg error "$output_message" '{"error": $error}')
        else
            local succeeded="true"
            local execution_time=$(($end_time - $start_time))
            local data=\"{}\"
        fi

        echo $(jq -n \
        --arg succeeded "$succeeded" \
        --arg execution_time "$execution_time" \
        --arg operation "$operation" \
        --argjson data "$data" \
        '{"operation": $operation ,"succeeded": $succeeded, "execution_time": $execution_time, "unit": "seconds", "data": $data}')
    )
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
#   - run_id: The resource group where the disk is located.
#
# Returns:
#   - true if the disk is attached, false otherwise.
#
get_disk_attached_state() {
    local disk_name=$1
    local run_id=$2
    [ "$(aws ec2 describe-volumes --volume-ids $disk_name --query "Volumes[].Status" --output text)" != "[]" ]
}

#Description
#   This function gets the operating system and size of a VM.
#
# Parameters:
#  - $1:  vm_name: the name of the VM instance (e.g. vm-1)
#
# Returns: JSON object containing the operating system and size of the VM
# Usage: get_vm_properties <vm_name>
get_vm_properties() {
    local vm_name=$1

    echo "$(aws ec2 describe-instances --instance-ids $vm_name --query "Reservations[].Instances[].{OperatingSystem:Platform, Size:InstanceType}" --output json)"
}

#Description
#   This function gets the region of a resource group.
#
# Parameters:
#  - $1:  run_id: the name of the resource group (e.g. c23f34-vf34g34g-3f34gf3gf4-fd43rf3f43)
#
# Returns: The region of the resource group
# Usage: get_region <run_id>
get_region() {
    local run_id=$1
        
    echo "$(aws ec2 describe-instances --filters "Name=tag:run_id,Values=$run_id" --query "Reservations[].Instances[].Placement.AvailabilityZone" --output text)"
}
