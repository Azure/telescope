#!/bin/bash

# DESC: Build the json used for logging results
# ARGS: $1 (optional): Compete scenario name
#       $2 (optional): Time taken to execute the compete scenario
#       $3 (optional): Whether the compete scenario was successful
#       $4 (optional): The cloud where the compete scenario was executed
#       $5 (optional): The region where the compete scenario was executed
#       $6 (optional): Additional json data to include in the json
# OUTS: The json
# NOTE: None
function build_json_output() {
    local operation_info=${1:-"{}"}
    local cloud_info=${2:-"{\"name\": \"azure\"}"}
    local region=${3:-"eastus"}
    

    local json_template=$(jq -n -c \
        --arg timestamp "$(get_timestamp)" \
        --argjson operation_info "$operation_info" \
        --arg region "$region" \
        --argjson cloud_info "$cloud_info" \
        '{
        "timestamp": $timestamp,
        "operation_info": $operation_info,
        "cloud_info": $cloud_info,
        "region": $region,
    }')

    echo "$json_template"
}

# DESC: Handle errors in the script
# ARGS: $1 (required): The exit status of the command that failed
#       $2 (required): The line number of the error
#       $3 (required): What compete scenario was being executed
#       $4 (required): The cloud where the compete scenario was executed
#       $5 (required): The region where the compete scenario was executed
#       $6 (required): The path to the error file
#       $7 (required): The path to the results file
# OUTS: None
# NOTE: This function is used to handle errors in the script. It read the errors from the error path and
#       writes them with in same json format in the result file. It also exits the script with the provided exit code. 
function script_trap_err() {
    local exit_code=1
    local lineno=$2
    local cloud=$3
    local region=$4
    local error_file=$5
    local results_file=$6

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
    local operation_info="$(build_operation_info_json "vm-redeploy" "false" "0" "seconds" "$json_error")"
    local cloud_info="$(build_cloud_info_json "$cloud" "{}")"

    local json_output="$(build_json_output "$operation_info" "$cloud_info" "$region")"
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

# DESC: Build the cloud info json
# ARGS: $1 (required): The cloud name
#       $2 (required): Json about the pre-provisioned VM
# OUTS: The json data
# NOTE: None
build_cloud_info_json() {
    local cloud=${1:-"azure"}
    local vm_info=${2:-"{}"}

    local json_data=$(jq -n -c \
        --arg cloud "$cloud" \
        --argjson vm_info "$vm_info" \
        '{
            "cloud": $cloud,
            "vm_info": $vm_info
        }')

    echo "$json_data"
}

# DESC: Get the data json 
# ARGS: $1 (required): The json view of the instance
# OUTS: The json data
# NOTE: None
build_operation_info_json() {
    local name=${1:-"vm-redeploy"}
    local succeeded=${2:-"false"}
    local time=${3:-"0"}
    local unit=${4:-"seconds"}
    local data=${5:-"{}"}

    local json_data=$(jq -n -c \
        --arg name "$name" \
        --arg succeeded "$succeeded" \
        --arg time "$time" \
        --arg unit "$unit" \
        --argjson data "$data" \
        '{
            "name": $name,
            "succeeded": $succeeded,
            "time": $time,
            "unit": $unit,
            "data": $data
        }')

    echo "$json_data"
}

# DESC: Get the current timestamp in format "2021-08-25T15:00:00Z"
# ARGS: None
# OUTS: The current timestamp
# NOTE: None
get_timestamp() {
  date -u +"%Y-%m-%dT%H:%M:%SZ"
}