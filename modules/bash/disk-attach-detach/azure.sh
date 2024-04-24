#!/bin/bash

# Description:
#   This function gets the name of disk instances.
#
# Parameters:
#  - $1: run_id: the ID of the test run (e.g. c23f34-vf34g34g-3f34gf3gf4-fd43rf3f43)
# 
# Returns: name of the VM instance
# Usage: get_vm_instances_by_run_id <run_id>
get_vm_instances_by_run_id() {
    local run_id=$1

    echo $(az resource list --resource-type Microsoft.Compute/virtualMachines --query "[?(tags.run_id == '$run_id')].name" --output tsv)
}

# Description:
#   This function gets the name of the disk instances.
#
# Parameters:
#  - $1: run_id: the ID of the test run (e.g. c23f34-vf34g34g-3f34gf3gf4-fd43rf3f43)
#
# Returns: name of the disk instances
# Usage: get_disk_instances_by_run_id <run_id>
get_disk_instances_by_run_id() {
    local run_id=$1
    
    echo "$(az resource list --resource-type Microsoft.Compute/disks --query "[?(tags.run_id == '${run_id}') && (managedBy==null)].name" --output tsv)"
}

# Description:
#   This function attaches or detaches a disk to/from a vm based on the operation parameter.
#
# Parameters:
#  - $1: operation: the operation to perform (attach or detach)
#  - $2: vm_name: the name of the VM instance (e.g. vm-1)
#  - $3: disk_name: the name of the disk instance (e.g. disk-1)
#  - $4: resource_group: the name of the resource group (e.g. c23f34-vf34g34g-3f34gf3gf4-fd43rf3f43)
#
# Returns: Information about each operation
# Usage: attach_or_detach_disk <operation> <vm_name> <disk_name> <resource_group>
attach_or_detach_disk() {
    local operation=$1
    local vm_name=$2
    local disk_name=$3
    local resource_group=$4

    start_time=$(date +%s)
    local output_message="$(az vm disk "$operation" -g "$resource_group" --vm-name "$vm_name" --name "$disk_name" 2>&1)"
    end_time=$(date +%s)
    
    echo "$(build_output "$operation" "$output_message" $(($end_time - $start_time)))"
}

# Description:
#   This function builds the output JSON object for the disk attach/detach operation.
#
# Parameters:
#  - $1: operation: the operation to perform (attach or detach)
#  - $2: output_message: the output message of the operation
#  - $3: execution_time: the execution time of the operation
#
# Returns: The operation result JSON object
# Usage: build_output <operation> <output_message> <execution_time>
build_output() {
    local operation=$1
    local output_message=$2
    local execution_time=$3

    set -Ee

    _catch() {
        echo '{"succeeded": "false", "time": "-1", "unit": "seconds", "data": {"error": "Unknown error"}}'
    }
    trap _catch ERR

    if [[ "$output_message" == "ERROR: "* ]]; then
        local succeeded="false"
        local execution_time=-1
        local data=$(jq -n -r -c --arg error "$output_message" '{"error": $error}')
    else
        local succeeded="true"
        local data=\"{}\"
    fi

    echo $(jq -n \
    --arg succeeded "$succeeded" \
    --arg execution_time "$execution_time" \
    --arg operation "$operation" \
    --argjson data "$data" \
    '{"name": $operation ,"succeeded": $succeeded, "time": $execution_time, "unit": "seconds", "data": $data}')
}
