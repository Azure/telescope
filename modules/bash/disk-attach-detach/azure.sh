#!/bin/bash

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
        --query "[?(tags.run_id == '$resource_group') && (managedBy==null)].name" \
        --output tsv)"
}

# Description:
#   This function gets the attach status of a disk based on the disk ID and resource group.
#
# Parameters:
#  - $1: disk_id: the ID of the disk
#  - $2: resource_group: the name of the resource group
#
# Returns: the attach status of the disk.
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
#  - $6: timeout(optional, default 300): the time out for the operation (e.g. 300)
# 
# Returns: Success status of the operation, execution time, error messages, additional messages if they exist.
# Usage: attach_or_detach_disk <operation> <vm_name> <disk_name> <resource_group> <index> [timeout]
attach_or_detach_disk() {
    local operation="$1"
    local vm_name="$2"
    local disk_name="$3"
    local resource_group="$4"
    local index="$5"
    local timeout="${6:-300}"

    local status_req
    if [ "$operation" == "attach" ]; then
        status_req="Attached"
    else
        status_req="Unattached"
    fi

    local internal_polling_result_file="/tmp/internal_polling_result-$(date +%s)" # Used to store the output of the background waitting process
    local external_polling_result_file="/tmp/external_polling_result-$(date +%s)" # Used to store the output of the foreground waitting process
    local start_time=$(date +%s)

    measure_disk_command "$operation" "$vm_name" "$disk_name" "$resource_group" > "$internal_polling_result_file" "$start_time" &

    wait_for_disk_status "$disk_name" "$resource_group" "$start_time" "$status_req" "$timeout" >"$external_polling_result_file" &

    # Wait for the operation to finish
    wait

    echo "$(build_output \
        "$operation" \
        "$external_polling_result_file" \
        "$internal_polling_result_file"\
    )"
}

# Description:
#   This function measures an operation on a disk.
#
# Parameters:
#  - $1: operation: the operation to perform (attach or detach)
#  - $2: vm_name: the name of the VM instance (e.g. vm-1)
#  - $3: disk_name: the name of the disk instance (e.g. disk-1)
#  - $4: resource_group: the name of the resource group (e.g. c23f34-vf34g34g-3f34gf3gf4-fd43rf3f43)
#  - $5: start_time: the start time of the operation (e.g. output of $(date +%s))
#
# Returns: Success status of the command, execution time or error.
# Usage: measure_disk_command <operation> <vm_name> <disk_name> <resource_group> <start_time>
measure_disk_command() {
    local operation="$1"
    local vm_name="$2"
    local disk_name="$3"
    local resource_group="$4"
    local start_time="$5"
    
    local internal_err_file="/tmp/internal_err_file-$(date +%s)"
    local internal_output_file="/tmp/internal_output_file-$(date +%s)"

    az vm disk \
        "$operation" \
        -g "$resource_group" \
        --vm-name "$vm_name" \
        --name "$disk_name" \
        2> "$internal_err_file" > "$internal_output_file"
        
    local end_time=$(date +%s)
    local exit_code=$?

    if [[ "$exit_code" -eq 0 ]]; then
        echo "$(jq -n \
            --arg output "$(cat "$internal_output_file")" \
            --arg time "$(($end_time - $start_time))" \
            '{ 
                "Succeeded": "true",
                "Output": $output,
                "Time": $time
            }'
        )"
    else
        echo "$(jq -n \
            --arg error "$(cat "$internal_err_file")" \
            '{ 
                "Succeeded": "false",
                "Error": $error
            }'
        )"
    fi
}

# Description:
#   This function waits for the disk status to change to the desired status.
#
# Parameters:
#  - $1: disk_name: the name of the disk instance (e.g. disk-1)
#  - $2: resource_group: the name of the resource group (e.g. c23f34-vf34g34g-3f34gf3gf4-fd43rf3f43)
#  - $3: start_time: the start time of the operation (e.g. output of $(date +%s))
#  - $4: status_req: the desired status of the disk (e.g. attach)
#  - $5: timeout(optional, default 300): the time out for the operation (e.g. 300)
#
# Returns: The success status of the operation and the execution time or error message
# Usage: wait_for_disk_status <disk_name> <resource_group> <start_time> <status_req> [timeout]
wait_for_disk_status() {
    local disk_name="$1"
    local resource_group="$2"
    local start_time="$3"
    local status_req="$4"
    local timeout="${5:-300}"

    local total_waited_time=0

    while [ "$total_waited_time" -lt "$timeout" ]; do
        local status=$(get_disk_attach_status_by_disk_id "$disk_name" "$resource_group")
        if [[ "$status" == "$status_req" ]]; then
            echo "{\"Succeeded\": \"true\", \"Time\": $(($(date +%s) - $start_time))}"
            break
        fi
        sleep 1
        total_waited_time=$((total_waited_time + 1))
    done

    if [[ "$total_waited_time" -ge "$timeout" ]]; then
        local json_result="{\"Succeeded\": \"false\", \"Error\": \"The operation has timed out\"}"
        echo "$json_result"
    fi
}

# Description:
#   This function builds the output JSON object for the disk attach/detach operation.
#
# Parameters:
#  - $1: operation: the operation to perform (attach or detach)
#  - $2: external_polling_result_file the path to the file containing the output of the external polling process
#  - $3: internal_polling_result_file the path to the file containing the output of the internal polling process
#
# Returns: The operation result JSON object
# Usage: build_output <operation> <external_polling_result_file> <internal_polling_result_file>
build_output() {
    local operation="$1"
    local external_polling_result_file="$2"
    local internal_polling_result_file="$3"

    set -Ee

    _catch() {
        echo '{"succeeded": "false", "time": "-1", "unit": "seconds", "data": {"error": "Unknown error"}}'
    }
    trap _catch ERR

    external_succeeded=$(jq -r '.Succeeded' "$external_polling_result_file")
    internal_succeeded=$(jq -r '.Succeeded' "$internal_polling_result_file")
    local err_message=""

    if [[ "$external_succeeded" == "true" ]]; then
        local external_polling_execution_time="$(jq -r '.Time' "$external_polling_result_file")"
    else
        local external_polling_execution_time=-1
        err_message="$(jq -r '.Error' "$external_polling_result_file")"
    fi

    if [[ "$internal_succeeded" == "true" ]]; then
        local internal_polling_execution_time="$(jq -r '.Time' "$internal_polling_result_file")"
    else
        local internal_polling_execution_time=-1
        err_message="$err_message $(jq -r '.Error' "$internal_polling_result_file")"
    fi

    if [[ $external_succeeded == "true" && $internal_succeeded == "true" ]]; then
        local succeeded="true"
        local data="{$(jq -r '.Output' "$internal_polling_result_file")}"
    else
        local succeeded="false"
        local data="{\"error\": \"$err_message\"}"
    fi

    echo "$(jq -n \
    --arg succeeded "$succeeded" \
    --arg external_polling_execution_time "$external_polling_execution_time" \
    --arg internal_polling_execution_time "$internal_polling_execution_time" \
    --arg operation "$operation" \
    --argjson data "$data" \
        '{ 
            "name": $operation ,
            "succeeded": $succeeded, 
            "internal_polling_execution_time": $internal_polling_execution_time,
            "external_polling_execution_time": $external_polling_execution_time,
            "unit": "seconds",
            "data": $data
        }'
    )"
}
