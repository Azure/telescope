#!/bin/bash
set -x
#Description
#   Function to execute tests
#
# Parameters:
#   - $1: run_id: the ID of the test run (e.g. c23f34-vf34g34g-3f34gf3gf4-fd43rf3f43)
#   - $2: scenario_type: the type of the scenario (e.g. perf-eval)
#   - $3: scenario_name: the name of the scenario (e.g. disk--attach-detach)
#   - $4: result_dir: the directory to store the test results (e.g. /mnt/results)
#   - $5 cloud: the cloud provider (e.g. azure))
#   - $6 iterations_number: the number of iterations to run the tests (e.g. 5, optional, default is 1)
#
# Returns: nothing
# Usage: execute <run_id> <scenario_type> <scenario_name> <result_dir> <cloud> <iterations_number>
execute() {
    local run_id=$1
    local scenario_type=$2
    local scenario_name=$3
    local result_dir=$4
    local cloud=$5
    local resource_group=$run_id
    local iterations_number=${6:-1}  # Set the default value of iterations_number to 1 if not provided

    mkdir -p $result_dir

    # get vm name and disk names
    local vm_name=$(get_vm_instance_by_name $run_id)

    # get VM operating system and size
    local vm_info=$(get_vm_properties $vm_name $resource_group)
    local vm_os=$(echo $vm_info | jq '.OperatingSystem')
    local vm_size=$(echo $vm_info | jq '.Size')
    local region=$(get_region $resource_group)

    for ((i=1; i<=iterations_number; i++)); do
        run_tests $run_id $vm_name $resource_group $vm_os $vm_size $region $i $cloud
    done
}

#Description
#   Function to run tests
#
# Parameters:
#   - $1: run_id: the ID of the test run (e.g. c23f34-vf34g34g-3f34gf3gf4-fd43rf3f43)
#   - $2: vm_name: the name of the virtual machine (e.g. vm-1)
#   - $3: resource_group: the resource group of the virtual machine (e.g. c23f34-vf34g34g-3f34gf3gf4-fd43rf3f43)
#   - $4: vm_os: the operating system of the virtual machine (e.g. Linux)
#   - $5: vm_size: the size of the virtual machine (e.g. Standard_LRS)
#   - $6: region: the region of the virtual machine (e.g. eastus))
#   - $7: run_index: the index of the test run (e.g. 1)
#   - $8: cloud: the cloud provider (e.g. azure)
#
# Returns: nothing
# Usage: run_tests <run_id> <vm_name> <resource_group> <vm_os> <vm_size> <region> <run_index> <cloud>
run_tests() {
    local vm_name=$2
    local resource_group=$3
    local vm_os=$4
    local vm_size=$5
    local region=$6
    local run_index=$7
    local cloud=$8

    local disk_names=($(get_disk_instances_by_name $resource_group))

    for index in "${!disk_names[@]}"; do
        disk_name="${disk_names[$index]}"
        measure_attach_detach "attach" $disk_name $vm_name $resource_group $run_index $cloud
        wait
    done

    for index in "${!disk_names[@]}"; do
        disk_name="${disk_names[$index]}"
        if [ "$(az disk show --name $disk_name --resource-group $resource_group --query "diskState" --output tsv)" == "Attached" ]; then
            measure_attach_detach "detach" $disk_name $vm_name $resource_group $run_index $cloud
            wait
        fi
    done
}

#Description
#   Function to attach or detach a disk to/from a virtual machine
#
# Parameters:
#   - $1: operation: the name of the operation (e.g. attach or detach)
#   - $2: disk_name: the name of the disk to attach or detach (e.g. disk-1)
#   - $3: vm_name: the name of the virtual machine (e.g. vm-1)
#   - $4: resource_group: the resource group of the virtual machine (e.g. c23f34-vf34g34g-3f34gf3gf4-fd43rf3f43)
#   - $5: run_index: the index of the test run (e.g. 1)
#   - $6: cloud: the cloud provider (e.g. azure)
#
# Returns: nothing, outputs data to files
# Usage: measure_attach_detach <operation> <disk_name> <vm_name> <resource_group> <run_index> <cloud>
measure_attach_detach() {
    local operation=$1
    local disk_name=$2
    local vm_name=$3
    local resource_group=$4
    local run_index=$5
    local cloud=$6

    start_time=$(date +%s)
    message="$(attach_detach_disk $operation $vm_name $disk_name $resource_group)"
    end_time=$(date +%s)
    if [[ $message == "ERROR: "* ]]; then
        result="fail"
        time=-1
    else
        result="success"
        time=$(($end_time - $start_time))
    fi

    if [ -z "$message" ]; then
        message="Operation completed successfully."
    fi

    output=$(fill_json_template $operation $result $time $disk_name $resource_group "$message" $cloud)
    filename="$result_dir/${disk_name}_${operation}_$run_index.json"
    echo $output > $filename
}

#Description
#   Function to fill a JSON template with the test results
#
# Parameters:
#   - $1: operation: the name of the operation (e.g. attach or detach)
#   - $2: result: the result of the operation (e.g. success or fail)
#   - $3: time: the time taken to complete the operation (e.g. 5)
#   - $4: disk_name: the name of the disk (e.g. disk-1)
#   - $5: resource_group: the resource group of the virtual machine (e.g. c23f34-vf34g34g-3f34gf3gf4-fd43rf3f43)
#   - $6: message: the message of the operation (e.g. Operation completed successfully.)
#   - $7: cloud: the cloud provider (e.g. azure)
#
# Returns: json with data
# Usage: fill_json_template <operation> <result> <time> <disk_name> <resource_group> <message> <cloud>
fill_json_template() {
    local operation=$1
    local result=$2
    local time=$3
    local disk_name=$4
    local resource_group=$5
    local message=$6
    local cloud=$7

    local disk_info=$(get_disk_storage_type_and_size $disk_name)

    (
        set -Ee
        trap _catch ERR

        local json_template=$(jq -n \
        --arg cloud "$cloud" \
        --arg region "$region" \
        --arg vm_name "$vm_name" \
        --arg vm_size "$vm_size" \
        --arg vm_os "$vm_os" \
        --arg operation "$operation" \
        --arg result "$result" \
        --argjson time $time \
        --arg unit "seconds" \
        --arg message "$message" \
        --arg disk_name "$disk_name" \
        --arg disk_size "$(echo $disk_info | jq -r '.[0].Size')" \
        --arg disk_type "$(echo $disk_info | jq -r '.[0].StorageType')" \
        --arg run_id "$run_id" \
        '{
            "cloud_info": {
                "cloud": $cloud,
                "region": $region,
                "vm_info": {
                    "vm_name": $vm_name,
                    "size": $vm_size,
                    "os": $vm_os
                }
            },
            "operation_info": {
                "operation": $operation,
                "result": $result,
                "time": $time,
                "unit": $unit,
                "message": $message
            },
            "disk_info": {
                "disk_name": $disk_name,
                "disk_size": $disk_size,
                "disk_type": $disk_type
            },
            "run_id": $run_id
        }')

        echo $json_template
    )
}

#Description
#   Function to catch errors
#
# Parameters: none
#
# Returns: json with data
# Usage: trap _catch ERR
_catch()
{
    local json_template=$(jq -n \
    --arg cloud "$cloud" \
    --arg region "$region" \
    --arg vm_name "$vm_name" \
    --arg vm_size "$vm_size" \
    --arg vm_os "$vm_os" \
    --arg operation "$operation" \
    --arg result "$result" \
    --argjson time $time \
    --arg unit "seconds" \
    --arg message "$message" \
    --arg disk_name "$disk_name" \
    --arg disk_size "$(echo $disk_info | jq -r '.[0].Size')" \
    --arg disk_type "$(echo $disk_info | jq -r '.[0].StorageType')" \
    --arg run_id "$run_id" \
    '{
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
    }')

    echo $json_template
}

# function to run disk test
# Parameters:
#   - disk_name: the name of the disk to test
#   - vm_name: the name of the virtual machine
#   - resource_group: the resource group of the virtual machine
#   - disk_size: the size of the disk
#   - run_id: the ID of the test run
#   - cloud: the cloud provider
run_alternate_tests() {
    local disk_name=$1
    local vm_name=$2
    local resource_group=$3
    local disk_size=$4
    local run_id=$5
    local cloud=$6

    attach_output=$(measure_attach_detach "attach" $disk_name $vm_name $resource_group $disk_size $run_id $cloud)
    attach_filename="$result_dir/$(cat /dev/urandom | tr -dc 'a-zA-Z0-9' | fold -w 32 | head -n 1).json"
    echo $attach_output > $attach_filename

    if [ "$(echo $attach_output | jq -r .$result_column)" == "success" ]; then
        detach_output=$(measure_attach_detach "detach" $disk_name $vm_name $resource_group $disk_size $run_id $cloud)
        detach_filename="$result_dir/$(cat /dev/urandom | tr -dc 'a-zA-Z0-9' | fold -w 32 | head -n 1).json"
        echo $detach_output > $detach_filename
    fi
}