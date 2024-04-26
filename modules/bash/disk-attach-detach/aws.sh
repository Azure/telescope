#!/bin/bash

# Description:
#   This function retrieves the VM instance by run id.

# Parameters:
#  - $1: run_id: the ID of the test run (e.g. c23f34-vf34g34g-3f34gf3gf4-fd43rf3f43)
# 
# Returns: The id of the VM instance
# Usage: get_vm_instance_by_run_id <run_id>
get_vm_instances_name_by_run_id() {
    local run_id=$1

    echo "$(aws ec2 describe-instances \
        --filters Name=tag:run_id,Values=$run_id Name=instance-state-name,Values=running \
        --query "Reservations[].Instances[0].InstanceId" \
        --output text)"
}

# Description:
#   This function gets the name of the disk instances by run id.
#
# Parameters:
#  - $1: run_id: the ID of the test run (e.g. c23f34-vf34g34g-3f34gf3gf4-fd43rf3f43)
#
# Returns: The names of the available disk instances
# Usage: get_available_disk_instances <run_id>
get_disk_instances_name_by_run_id() {
    local run_id=$1
    
    echo "$(aws ec2 describe-volumes \
        --filters Name=status,Values=available Name=tag:run_id,Values=$run_id \
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
#  - $5: index: the index of the disk
# Returns: Error message of the operation otherwise nothing
# Usage: attach_or_detach_disk <operation> <vm_name> <disk_name> <run_id> <index>
attach_or_detach_disk() {
    local operation=$1
    local vm_name=$2
    local disk_name=$3
    local run_id=$4
    local index=$5
    local timeout=90 # seconds to wait for the operation to complete
    local all_devices_suffixes=("f" "g" "h" "i" "j" "k" "l" "m" "n" "o" "p")

    local start_time=$(date +%s)
    local status_req=$(if [ "$operation" == "attach" ]; 
        then echo "attached"; 
        else echo ""; fi)
    
    aws ec2 $operation-volume \
        --volume-id $disk_name \
        --instance-id $vm_name \
        --device "/dev/sd${all_devices_suffixes[$index]}" \
        2> /tmp/$vm_name-$disk_name-$operation.error \
        >  /dev/null
    error_code=$?
    local error_message=$(cat /tmp/$vm_name-$disk_name-$operation.error)
    if [[ $error_code -ne 0 ]]; then
        echo $(build_output "false" "-1" "$operation" "$(jq -n --arg msg "$error_message" '{"error": $msg}')")
        return
    fi
    for ((i=1; i<=$timeout; i++)); do
        local status=$(
            aws ec2 describe-volumes \
                --volume-ids $disk_name \
                --query "Volumes[].Attachments[].State" \
                --output text)
        if [ "$status" == "$status_req" ]; then
            break
        fi
        sleep 1
    done
    
    local execution_time=$(( $(date +%s) - $start_time ))
    if [ $execution_time -gt $timeout ]; then
        echo $(build_output "false" "-1" "$operation" "$(jq -n --arg msg "The disk $operation operation timed out." '{"error": $msg}')")
    else
        echo $(build_output "true" "$execution_time" "$operation" "$(jq -n '{}')")
    fi
}

# Description:
#   This function builds the output JSON object for the disk attach/detach operation.
#
# Parameters:
#  - $1: succeeded: whether the operation succeeded or not
#  - $2: execution_time: the execution time of the operation
#  - $3: operation: the name of the operation
#  - $4: data: additional data related to the operation
#
# Returns: None
# Usage: print_result <succeeded> <execution_time> <operation> <data>
build_output() {
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