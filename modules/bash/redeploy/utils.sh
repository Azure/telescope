#!/bin/bash

# DESC: Build the json used for logging results
# ARGS: $1 (optional): Compete scenario name
#       $2 (optional): Time taken to execute the compete scenario
#       $3 (optional): Whether the compete scenario was successful
#       $4 (optional): Additional json data to include in the json
# OUTS: The json
# NOTE: None

function get_json_output() {
    local operation_info=${1:-"compete-operation"}
    local execution_time=${2:-"0"}
    local succeeded=${3:-"true"}
    local cloud=${4:-"azure"}
    local region=${5:-"eastus"}
    local data=${6:-"{}"}
    

    local json_template=$(jq -n -c \
        --arg timestamp "$(date +%s)" \
        --arg operation_info "$operation_info" \
        --arg succeeded "$succeeded" \
        --arg execution_time "$execution_time" \
        --arg cloud "$cloud" \
        --arg region "$region" \
        --argjson data "${data}" \
        '{
        "operation_info": $operation_info,
        "$execution_time": $execution_time,
        "success": $succeeded,
        "cloud": $cloud,
        "region": $region,
        "data": $data
    }')

    echo "$json_template"
}
# DESC: Handle errors in the script
# ARGS: $1 (required): The exit status of the command that failed
#       $2 (required): The line number of the error
#       $3 (required): What compete scenario was being executed
#       $4 (required): The path to the file where the error was written
#       $5 (required): The path to the file where the results will be written
# OUTS: None
# NOTE: This function is used to handle errors in the script. It read the errors from the error path and
#       writes them with in same json format in the result file. It also exits the script with the provided exit code. 
function script_trap_err() {
    local exit_code=1
    local lineno = $2
    local operation_info=$3
    local cloud=$4
    local region=$5
    local error_file=$6
    local results_file=$7

    # Disable the error trap handler to prevent potential recursion
    trap - ERR

    # Consider any further errors non-fatal to ensure we run to completion
    set +o errexit
    set +o pipefail

    # Validate any provided exit code
    if [[ ${1-} =~ ^[0-9]+$ ]]; then
        exit_code="$1"
    fi

    local error="$(cat "$error_file")"
    local json_error=$(jq -n -c \
        --arg error "$error" \
        '{
        "error": $error,
        "line": $lineno,
        "exit_status": $exit_code
    }')

    local json_output="$(get_json_output "$operation_info" "0" "false" "$cloud" "$region" "$json_error")"
    echo "$json_output" > "$(printf "$results_file" "error")"
    # Exit with failure status
    exit "$exit_code"
}

# DESC: Get the name of the virtual machine instances by run id
# ARGS: $1 (required): The run id
# OUTS: The name of the virtual machine instances
# NOTE: The run id is usually the resource group name
get_vm_instances_name_by_run_id() {
    local resource_group=$1

    echo $(az resource list \
        --resource-type Microsoft.Compute/virtualMachines \
        --query "[?(tags.run_id == '"$resource_group"')].name" \
        --output tsv)
}

# DESC: Get the instance view for a vm
# ARGS: $1 (required): The resource group of the VM
#       $2 (required): The name of the VM
# OUTS: The json of the instance view
# NOTE: None
get_vm_instance_view_json() {
    local resource_group=$1
    local vm_name=$2

    echo $(az vm get-instance-view --resource-group $1 --name $2 )
}

# DESC: Get the data json 
# ARGS: $1 (required): The json view of the instance
# OUTS: The json data
# NOTE: None
build_data_json() {
    local vm_info=$1

    local json_data=$(jq -n -c \
        --argjson vm_info "$vm_info" \
        '{
            "vm_info": $vm_info
    }')

    echo "$json_data"
}