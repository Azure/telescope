#!/bin/bash

# DESC: Build the json used for logging results
# ARGS: $1 (optional): Json that includes the data for the operation
#       $2 (optional): Json that includes the data about the resources pre-provisioned
# OUTS: The json with the results
# NOTE: None
function utils::build_json_output() {
    local operation_info=${1:-"{}"}
    local cloud_info=${2:-"{\"name\": \"azure\"}"}
    
    local json_template=$(jq -n -c \
        --arg timestamp "$(utils::get_timestamp)" \
        --argjson operation_info "$operation_info" \
        --argjson cloud_info "$cloud_info" \
        '{
            "timestamp": $timestamp,
            "operation_info": $operation_info,
            "cloud_info": $cloud_info,
        }')

    echo "$json_template"
}

# DESC: Handle errors in the script
# ARGS: $1 (optional): The exit status of the command that failed (default: 1)
#       $2 (required): The line number of the error
#       $3 (required): The path to the error file
#       $4 (required): The path to the results file
# OUTS: None
# NOTE: This function is used to handle errors in the script. It reads the errors from the error path and
#       writes them with in same json format in the result file. 
#       It also exits the script with the provided exit code if it is numerical, if not it exits with 1. 
function utils::script_trap_err() {
    local exit_code=1
    local lineno=$2
    local error_file="$RESULT_DIR/$SCENARIO_NAME-error.txt"

    # Disable the error trap handler to prevent potential recursion
    trap - ERR

    # Consider any further errors non-fatal to ensure we run to completion
    set +o errexit
    set +o pipefail
    set +o xtrace
    # Validate any provided exit code
    if [[ ${1-} =~ ^[0-9]+$ ]]; then
        exit_code="$1"
    fi

    local json_error=$(jq -n -c \
        --arg lineno "$lineno" \
        --arg exit_code "$exit_code" \
        '{
            "line": $lineno,
            "exit_status": $exit_code
        }')
    echo $json_error
    echo $json_error >> "$error_file"
    
    # Exit with failure status
    exit "$exit_code"
}

# DESC: Build an error message json
# ARGS: $1 (required): The error message
# OUTS: The json data
# NOTE: None
function utils::build_error_message() {
    local error=${1:-""}
    local error_type=${2:-"error"}

    local json_error=$(jq -n -c \
        --arg error "$error" \
        --arg error_type "$error_type" \
        '{
            "error": $error
            "type": $error_type
        }')

    echo "$json_error"
}

# DESC: Build the cloud info json
# ARGS: $1 (required): Json about the pre-provisioned VM 
# OUTS: The json data
# NOTE: None
function utils::build_cloud_info_json() {
    local vm_info=${1:-"{}"}

    local json_data=$(jq -n -c \
        --argjson vm_info "$vm_info" \
        '{
            "vm_info": $vm_info
        }')

    echo "$json_data"
}

# DESC: Build the operation info json 
# ARGS: $1 (required): The json view of the instance
#       $2 (required): If the VM was successful
#       $3 (required): The time taken to execute the compete scenario
#       $4 (required): The unit of the time taken
#       $5 (required): Additional json data
# OUTS: The json data
# NOTE: None
function utils::build_operation_info_json() {
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
function utils::get_timestamp() {
  date -u +"%Y-%m-%dT%H:%M:%SZ"
}


# DESC: Wait for SSH connection to be established
# ARGS: $1 (required): The hostname to connect to
#       $2 (required): The port to connect to
#       $3 (required): The timeout in seconds
# OUTS: None
# NOTE: This function waits until an SSH connection can be established to the specified hostname.
function utils::test_connection() {
    local ip=$1
    local port=$2
    local timeout=$3

    local output=1
    local try=0
    local wait_time=3

    while [ $output -ne 0 ] && [ $try -lt $timeout ]; do 
        output=$(($(netcat -w $wait_time -z $ip $port &> /dev/null && echo 0 || echo 1)))
        try=$((try + $wait_time + 1))
        sleep 1
    done

    if [ $try -lt $timeout ]; then
        echo "true"
    else
        echo "false"
    fi
}


# DESC: Wait for SSH connection to be established
# ARGS: $1 (required): The hostname to connect to
#       $2 (optional): The timeout for the connection
# OUTS: None
# NOTE: This function waits until an SSH connection can be established to the specified hostname.
utils::wait_ssh_connection() {
    local hostname=$1
    local timeout=${2:-60}
    local try=0
    exit_code=$(ssh-keyscan -T $timeout $hostname >/dev/null 2>&1)

    while [ $? -ne 0 ] && [ $try -lt $timeout ]; do
        sleep 1
        try=$((try + 1))
        exit_code=$(ssh-keyscan $hostname >/dev/null 2>&1)
    done
    if [ $try -eq $timeout ]; then
        exit 1
    fi
}

# DESC: Log a message and display the details of a VM redeploy
# ARGS:
#   $1 (optional): The name of the VM (default: "")
#   $2 (optional): The size of the VM (default: "")
#   $3 (optional): The OS of the VM (default: "")
#   $4 (optional): The OS type of the VM (default: "")
#   $5 (optional): The region of the VM (default: "")
#   $6 (optional): The cloud provider (default: "")
#   $7 (optional): Timeout for ssh connection (default: "")
# OUTS: None
# NOTE: This function logs a message and displays the details of a VM redeploy, including the VM name, size, OS, region, and timeout.
function utils::write_log() {
    local vm_name=${1-""}
    local vm_size=${2-""}
    local vm_os=${3-""}
    local vm_os_type=${4-""}
    local region=${5-""}
    local cloud=${6-""}
    local timeout=${7-""}

    echo "Measuring $cloud VM redeploy with the following details: 
    - VM name: $vm_name
    - VM size: $vm_size
    - VM OS: $vm_os
    - VM OS type: $vm_os_type
    - Region: $region
    - Timeout: $timeout"
}