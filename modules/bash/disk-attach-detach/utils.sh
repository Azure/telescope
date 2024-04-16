#!/bin/bash

#Description
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
# Usage: execute <run_id> <scenario_type> <scenario_name> <result_dir> <cloud> <iterations_number>
execute() {
    local run_id=$1
    local scenario_type=$2
    local scenario_name=$3
    local result_dir=$4
    local cloud=$5
    local region=$6
    local iterations_number=${7:-1}  # Set the default value of iterations_number to 1 if not provided

    mkdir -p $result_dir

    # get vm name and disk names
    local vm_name=$(get_vm_instance_by_name $run_id)

    for ((i=1; i<=iterations_number; i++)); do
        run_tests $run_id $vm_name $i $cloud
    done
}

#Description
#   Function to run tests
#
# Parameters:
#   - $1: resource_group: the resource group of the virtual machine (e.g. c23f34-vf34g34g-3f34gf3gf4-fd43rf3f43)
#   - $2: vm_name: the name of the virtual machine (e.g. vm-1)
#   - $3: run_index: the index of the run (e.g. 1)
#   - $4: cloud: the cloud provider (e.g. azure)
#
# Returns: nothing
# Usage: run_tests <run_id> <vm_name> <resource_group> <vm_os> <vm_size> <region> <run_index> <cloud>
run_tests() {
    local resource_group=$1
    local vm_name=$2
    local run_index=$3
    local cloud=$4

    local disk_names=($(get_disk_instances_by_name $resource_group))

    for index in "${!disk_names[@]}"; do
        disk_name="${disk_names[$index]}"
        operation_info="$(attach_or_detach_disk "attach" "$vm_name" "$disk_name" "$resource_group")"
        wait
        output=$(fill_json_template "$operation_info")
        filename="$result_dir/${disk_name}_attach_$run_index.json"
        echo $output > $filename
    done

    for index in "${!disk_names[@]}"; do
        disk_name="${disk_names[$index]}"
        operation_info="$(attach_or_detach_disk "detach" "$vm_name" "$disk_name" "$resource_group")"
        wait
        output=$(fill_json_template "$operation_info")
        filename="$result_dir/${disk_name}_detach_$run_index.json"
        echo $output > $filename
    done
}

#Description
#   Function to fill a JSON template with the test results
#
# Parameters:
#   - $1: operation: the operation to perform (e.g. attach)
#
# Returns: json with data
# Usage: fill_json_template <operation> <result> <time> <disk_name> <resource_group> <message> <cloud>
fill_json_template() {
    local operation_info="$1"

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

#Description
# Function to catch errors
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
            "execution_time": "",
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