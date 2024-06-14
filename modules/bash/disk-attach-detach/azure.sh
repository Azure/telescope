#!/bin/bash

# Description:
#   This function gets the VM instance name by resource group(run id).
#
# Parameters:
#  - $1: run_id: the ID of the test run (e.g. c23f34-vf34g34g-3f34gf3gf4-fd43rf3f43)
# 
# Returns: name of the VM instance
# Usage: get_vm_instances_by_run_id <run_id>
get_vm_instances_name_by_run_id() {
    local resource_group=$1

    echo $(az resource list \
        --resource-type Microsoft.Compute/virtualMachines \
        --query "[?(tags.run_id == '"$resource_group"')].name" \
        --output tsv)
}

# Description:
#   This function gets the name of the disk instances by resource group(run id).
#
# Parameters:
#  - $1: run_id: the ID of the test run (e.g. c23f34-vf34g34g-3f34gf3gf4-fd43rf3f43)
#
# Returns: name of the disk instances
# Usage: get_disk_instances_by_run_id <run_id>
get_disk_instances_name_by_run_id() {
    local resource_group=$1
    
    echo "$(az resource list \
        --resource-type Microsoft.Compute/disks \
        --query "[?(tags.run_id == '"$resource_group"') && (managedBy==null)].name" \
        --output tsv)"
}

# Description:
#   This function gets the attach status of a disk based on the disk ID and resource group.
#
# Parameters:
#  - $1: disk_id: the ID of the disk
#  - $2: resource_group: the name of the resource group
#
# Returns: the attach status of the disk
# Usage: get_disk_attach_status_by_disk_id <disk_id> <resource_group>
get_disk_attach_status_by_disk_id() {
    local disk_id=$1
    local resource_group=$2

    echo "$(az disk show \
        --name "$disk_id" \
        --resource-group "$resource_group" \
        --query "{diskState:diskState}" \
        --output tsv)"
}

# Description:
#   This function attaches or detaches a disk to/from a vm based on the operation parameter.
#
# Parameters:
#  - $1: operation: the operation to perform (attach or detach)
#  - $2: vm_name: the name of the VM instance (e.g. vm-1)
#  - $3: disk_name: the name of the disk instance (e.g. disk-1)
#  - $4: resource_group: the name of the resource group (e.g. c23f34-vf34g34g-3f34gf3gf4-fd43rf3f43)
#  - $5: index: the index of the disk (not used in Azure)
# 
# Returns: Information about each operation
# Usage: attach_or_detach_disk <operation> <vm_name> <disk_name> <resource_group>
attach_or_detach_disk() {
    local operation=$1
    local vm_name=$2
    local disk_name=$3
    local resource_group=$4
    local index=$5
    local filename=&6

    set -x

    local status_req=$(if [ "$operation" == "attach" ]; 
    then echo "Attached"; 
    else echo "Unattached"; fi)

    local attach_command=$(
    start_time=$(date +%s)
    local output_message="$(az vm disk "$operation" -g "$resource_group" --vm-name "$vm_name" --name "$disk_name" 2>&1)"
    end_time=$(date +%s)
    echo "$(build_output "$operation" "$output_message" "$(($end_time - $start_time))")" > "$filename"
    )
    
    local output_message="ERROR : Telescope polling timed out."
    start_time=$(date +%s)
    for ((i=1; i<=90; i++)); do
        local status=$(get_disk_attach_status_by_disk_id "$disk_name" "$resource_group")
        if [ "$status" == "$status_req" ]; then
            
            break
        fi
        sleep 1
    done
    end_time=$(date +%s)

    echo "$(build_output "$operation" "$output_message" "$(($end_time - $start_time))")"
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
