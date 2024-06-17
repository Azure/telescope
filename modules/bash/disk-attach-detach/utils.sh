#!/bin/bash

# Description
#   Function to execute tests
#
# Parameters:
#   - $1: run_id: the ID of the test run (e.g. c23f34-vf34g34g-3f34gf3gf4-fd43rf3f43)
#   - $2: scenario_type: the type of the scenario (e.g. perf-eval)
#   - $3: scenario_name: the name of the scenario (e.g. disk--attach-detach)
#   - $4: result_dir: the directory to store the test results (e.g. /mnt/results)
#   - $5 cloud: the cloud provider (e.g. azure))
#   - $6 region: the region of the virtual machine (e.g. eastus))
#   - $7 iterations_number: the number of iterations to run the tests (e.g. 5, optional, default is 1)
#
# Returns: nothing
# Usage: execute <run_id> <scenario_type> <scenario_name> <result_dir> <cloud> <region> [iterations_number]
execute() {
    local run_id=$1
    local scenario_type=$2
    local scenario_name=$3
    local result_dir=$4
    local cloud=$5
    local region=$6
    local iterations_number=${7:-1}  # Set the default value of iterations_number to 1 if not provided

    mkdir -p "$result_dir"

    # get vm name and disk names
    local vm_name=$(get_vm_instances_name_by_run_id "$run_id")

    for ((i=1; i <= $iterations_number; i++)); do
        run_and_collect "$run_id" "$vm_name" "$i" "$cloud"
    done
}

# Description
#   Function to run tests and collect results
#
# Parameters:
#   - $1: run_id: the resource group of the virtual machine (e.g. c23f34-vf34g34g-3f34gf3gf4-fd43rf3f43)
#   - $2: vm_name: the name of the virtual machine (e.g. vm-1)
#   - $3: run_index: the index of the run (e.g. 1)
#   - $4: cloud: the cloud provider (e.g. azure)
#
# Returns: nothing
# Usage: run_and_collect <run_id> <vm_name> <run_index> <cloud>
run_and_collect() {
    local run_id=$1
    local vm_name=$2
    local run_index=$3
    local cloud=$4

    local disk_names=($(get_disk_instances_name_by_run_id "$run_id"))

    for index in "${!disk_names[@]}"; do
        disk_name="${disk_names[$index]}"
        local temp_file=$(head -c 10 /dev/random)
        operation_info="$(attach_or_detach_disk "attach" "$vm_name" "$disk_name" "$run_id" "$index" "$temp_file")"
        wait

        succeeded=$(echo "$operation_info" | jq -r '.succeeded')
        if [ "$succeeded" == "false" ]; then
            unset disk_names[$index] # Prevents detach operation if attach operation fails
        fi

        for line in $(cat $filename)
        do
            output=$(fill_json_template "$line")
            local random_character=$(head -c 5 /dev/random)
            filename="$result_dir/${disk_name}_$run_index_$random_character.json"
            echo "$output" > "$filename"
        done
    done

    for index in "${!disk_names[@]}"; do
        disk_name="${disk_names[$index]}"
        if [ -z "$disk_name" ]; then # Skip disks that failed to attach
            continue
        fi
        operation_info="$(attach_or_detach_disk "detach" "$vm_name" "$disk_name" "$run_id" "$index")"
        wait
        output=$(fill_json_template "$operation_info")
        filename="$result_dir/${disk_name}_detach_$run_index.json"
        echo "$output" > "$filename"
    done
}

# Description
#   Function to fill a JSON template with the test results
#
# Parameters:
#   - $1: operation: execution info of the operator (e.g. attach)
#
# Returns: json with data
# Usage: fill_json_template <operation_info>
fill_json_template() {
    local operation_info=$1

    (
        set -Ee
        trap _catch ERR

        local json_template=$(jq -n -c \
        --argjson operation_info "$operation_info" \
        '{
            "operation_info": $operation_info,
        }')

        echo "$json_template"
    )
}

# Description
#   Function to catch errors
#
# Parameters: none
#
# Returns: json with data
# Usage: trap _catch ERR
_catch()
{
    echo "{
        "cloud_info": {
            "cloud": "",
            "region": "",
            "vm_info": {
                "vm_name": "",
                "size": "",
                "os": ""
            }
        },
        "operation_info": {
            "operation": "",
            "result": "",
            "time": "",
            "unit": "",
            "message": "Unknown error"
        },
        "disk_info": {
            "disk_name": "",
            "disk_size": "",
            "disk_type": ""
        },
        "run_id": ""
    }"
}