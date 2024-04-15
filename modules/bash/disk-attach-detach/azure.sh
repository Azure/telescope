#!/bin/bash

# Description:
#   This script contains the functions to manage the resources in the resource group.
#
# Parameters:
#  - $1: run_id: the ID of the test run (e.g. c23f34-vf34g34g-3f34gf3gf4-fd43rf3f43)
# 
# Returns: name of the VM instance
# Usage: get_vm_instance_by_name <run_id>
get_vm_instance_by_name() {
    local run_id=$1

    echo $(az resource list --resource-type Microsoft.Compute/virtualMachines --query "[?(tags.run_id == '$run_id')].name" --output tsv)
}

# Description:
#   This function gets the disk instances by name.
#
# Parameters:
#  - $1: run_id: the ID of the test run (e.g. c23f34-vf34g34g-3f34gf3gf4-fd43rf3f43)
#
# Returns: name of the disk instances
# Usage: get_disk_instances_by_name <run_id>
get_disk_instances_by_name() {
    local run_id=$1
    
    echo "$(az resource list --resource-type Microsoft.Compute/disks --query "[?(tags.run_id == '${run_id}')].name" --output tsv)"
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
# Returns: Error message of the operation otherwise nothing
# Usage: attach_or_detach_disk <operation> <vm_name> <disk_name> <resource_group>
attach_or_detach_disk() {
    local operation=$1
    local vm_name=$2
    local disk_name=$3
    local resource_group=$4

    start_time=$(date +%s)
    local output_message="$(az vm disk $operation -g $resource_group --vm-name ${vm_name} --name ${disk_name} 2>&1)"
    end_time=$(date +%s)
    
    echo "$(build_output $operation "$output_message" $(($end_time - $start_time)))"
}

# Description:
#   This function validates the resources in the resource group.
#
# Parameters:
#  - $1: run_id: the ID of the test run (e.g. c23f34-vf34g34g-3f34gf3gf4-fd43rf3f43)
#
# Returns: None
# Usage: validate_resources <run_id>
validate_resources() {
    local run_id=$1
    
    # Retrieve VMs from the resource group
    vm_count=$(az vm list --resource-group $run_id --query "length([])")

    # Check if there is only one VM
    if [ $vm_count -ne 1 ]; then
        echo "Error: There should be exactly one VM in the resource group, but ${vm_count} were found."
        exit 1
    fi

    # Retrieve disks from the resource group
    disk_count=$(az disk list --resource-group $run_id --query "length([])")

    # Check if there is at least one disk
    if [ $disk_count -lt 1 ]; then
        echo "Error: There should be at least one disk in the resource group, but ${disk_count} were found"
        exit 1
    fi
}

# Description:
#   This function gets the region of a resource group.
#
# Parameters:
#  - $1: resource_group: the name of the resource group (e.g. c23f34-vf34g34g-3f34gf3gf4-fd43rf3f43)
#
# Returns: The region of the resource group
# Usage: get_region <resource_group>
get_region() {
    local resource_group=$1
        
    echo $(az group show --name $resource_group --query "location" --output tsv)
}

# Description:
#   This function builds the output JSON object for the disk attach/detach operation.
#
# Parameters:
#  - $1: operation: the operation to perform (attach or detach)
#  - $2: output_message: the output message of the operation
#  - $3: start_time: the start time of the operation
#  - $4: end_time: the end time of the operation
#
# Returns: The output JSON object
# Usage: build_output <operation> <output_message> <start_time> <end_time>
build_output() {
    local operation=$1
    local output_message=$2
    local execution_time=$3

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
        local data=\"{}\"
    fi

    echo $(jq -n \
    --arg succeeded "$succeeded" \
    --arg execution_time "$execution_time" \
    --arg operation "$operation" \
    --argjson data "$data" \
    '{"name": $operation ,"succeeded": $succeeded, "time": $execution_time, "unit": "seconds", "data": $data}')
}
