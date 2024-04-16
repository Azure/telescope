#!/bin/bash

# Description:
#   This function retrieves the VM instance by run id.

# Parameters:
#  - $1: run_id: the ID of the test run (e.g. c23f34-vf34g34g-3f34gf3gf4-fd43rf3f43)
# 
# Returns: The id of the VM instance
# Usage: get_vm_instance_by_run_id <run_id>
get_vm_instance_by_run_id() {
    local run_id=$1

    echo "$(aws ec2 describe-instances \
        --filters "Name=tag:run_id,Values=$run_id" \
        --query "Reservations[].Instances[].InstanceId" \
        --output text)"
}

# Description:
#   This function retrieves the disk instances by run id that are available in the specified region.
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
#   This function prints the result of an operation.
#
# Parameters:
#  - $1: succeeded: whether the operation succeeded or not
#  - $2: execution_time: the execution time of the operation
#  - $3: operation: the name of the operation
#  - $4: data: additional data related to the operation
#
# Returns: None
# Usage: print_result <succeeded> <execution_time> <operation> <data>
print_result() {
    local succeeded=$1
    local execution_time=$2
    local operation=$3
    local data=$4

    echo $(jq -n \
        --arg succeeded "$succeeded" \
        --arg execution_time "$execution_time" \
        --arg operation "$operation" \
        --argjson data "$data" \
        '{"operation": $operation ,"succeeded": $succeeded, "execution_time": $execution_time, "unit": "seconds", "data": $data}')
}

# Description:
#   This function attaches or detaches a disk to/from a VM based on the operation parameter.
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
    local timeout=30 # seconds to wait for the operation to complete

    local start_time=$(date +%s)
    
    if [ "$operation" == "attach" ]; then
        local output_message="$(aws ec2 attach-volume --volume-id $disk_name --instance-id $vm_name --device /dev/sdf)"
        if [ -z "$output_message" ]; then
            echo $(print_result "false" "-1" "$operation" "{\"error\": \"Failed to $operation volume.\"}")
            return
        fi
        for ((i=1; i<=$timeout; i++)); do
            local status=$(aws ec2 describe-volumes --volume-ids $disk_name --query "Volumes[].Attachments[].State" --output text)
            if [ "$status" == "attached" ]; then
                break
            fi
            sleep 1
        done

    elif [ "$operation" == "detach" ]; then
        local output_message="$(aws ec2 detach-volume --volume-id $disk_name)"
        if [ -z "$output_message" ]; then
            echo $(print_result "false" "-1" "$operation" "{\"error\": \"Failed to $operation volume.\"}")
            return
        fi
        for ((i=1; i<=$timeout; i++)); do
            local status=$(aws ec2 describe-volumes --volume-ids $disk_name --query "Volumes[].State" --output text)
            if [ "$status" == "available" ]; then
                break
            fi
            sleep 1
        done
    else
        echo "Invalid operation. Please specify either 'attach' or 'detach'."
        exit 1
    fi
    
    local execution_time=$(( $(date +%s) - $start_time ))
    if [ $execution_time -gt $timeout ]; then
        echo $(print_result "false" "-1" "$operation" "{\"error\": \"Disk $operation operation timed out.\"}")
    else
        echo $(print_result "true" "$execution_time" "$operation" "{}")
    fi
}