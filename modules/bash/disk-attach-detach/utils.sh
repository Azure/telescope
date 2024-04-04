#!/bin/bash

# function to execute tests
execute() {
    local run_id=$1
    local scenario_type=$2
    local scenario_name=$3
    local result_dir=$4
    local resource_group=$run_id
    local iterations_number=${5:-1}  # Set the default value of iterations_number to 1 if not provided

    mkdir -p $result_dir

    # get vm name and disk names
    local vm_name=$(get_vm_instance_by_name $run_id)

    # get VM operating system and size
    local vm_os=$(get_vm_os $vm_name $resource_group)
    local vm_size=$(get_vm_size $vm_name $resource_group)
    local region=$(get_region $resource_group)

    for ((i=1; i<=iterations_number; i++)); do
        run_tests $run_id $vm_name $resource_group $vm_os $vm_size $region $i
    done
}

# function to run tests
run_tests() {
    local vm_name=$2
    local resource_group=$3
    local vm_os=$4
    local vm_size=$5
    local region=$6
    local run_index=$7

    local disk_names=($(get_disk_instances_by_name $resource_group))

    for index in "${!disk_names[@]}"; do
        disk_name="${disk_names[$index]}"
        measure_attach $disk_name $vm_name $resource_group $run_index
        wait
    done

    for index in "${!disk_names[@]}"; do
        disk_name="${disk_names[$index]}"
        if [ "$(az disk show --name $disk_name --resource-group $resource_group --query "diskState" --output tsv)" == "Attached" ]; then
            measure_detach $disk_name $vm_name $resource_group $run_index
            wait
        fi
    done
}

# function to measure attach operation
measure_attach() {
    local disk_name=$1
    local vm_name=$2
    local resource_group=$3
    local run_index=$4

    start_time=$(date +%s)
    attach_message="$(attach_disk $vm_name $disk_name $resource_group)"
    end_time=$(date +%s)
    if [[ $attach_message == "ERROR: {"* ]]; then
        attach_time=-1
        attach_result="failed"
    else
        attach_time=$(($end_time - $start_time))
        attach_result="success"
    fi

    attach_output=$(fill_json_template "attach" $attach_result $attach_time $disk_name $resource_group $attach_message)
    attach_filename="$result_dir/${disk_name}_attach_$run_index.json"
    echo $attach_output > $attach_filename
}

# function to measure detach operation
measure_detach() {
    local disk_name=$1
    local vm_name=$2
    local resource_group=$3
    local run_index=$4

    start_time=$(date +%s)
    detach_message="$(detach_disk $vm_name $disk_name $resource_group)"
    end_time=$(date +%s)
    if [[ $detach_message == "ERROR: {"* ]]; then
        detach_time=-1
        detach_result="failed"
    else
        detach_time=$(($end_time - $start_time))
        detach_result="success"
    fi

    detach_output=$(fill_json_template "detach" $detach_result $detach_time $disk_name $resource_group $detach_message)
    detach_filename="$result_dir/${disk_name}_detach_$run_index.json"
    echo $detach_output > "$detach_filename"
}

# function to run disk test
run_alternate_tests() {
    local disk_name=$1
    local vm_name=$2
    local resource_group=$3
    local disk_size=$4
    local run_id=$5

    attach_output=$(measure_attach $disk_name $vm_name $resource_group $disk_size $run_id)
    attach_filename="$result_dir/$(cat /dev/urandom | tr -dc 'a-zA-Z0-9' | fold -w 32 | head -n 1).json"
    echo $attach_output > $attach_filename

    if [ "$(echo $attach_output | jq -r .$result_column)" == "success" ]; then
        detach_output=$(measure_detach $disk_name $vm_name $resource_group $disk_size $run_id)
        detach_filename="$result_dir/$(cat /dev/urandom | tr -dc 'a-zA-Z0-9' | fold -w 32 | head -n 1).json"
        echo $detach_output > $detach_filename
    fi
}

# function to fill the JSON template with received parameters
fill_json_template() {
    local operation=$1
    local result=$2
    local result_time=$3
    local disk_name=$4
    local run_id=$5
    local message=$6

    local timestamp=$(date)
    local disk_info=$(get_disk_storage_type_and_size $disk_name)

    (
        set -Ee
        trap _catch ERR

        local json_template=$(jq -n \
        --arg timestamp "$timestamp" \
        --arg cloud "$cloud" \
        --arg region "$region" \
        --arg vm_name "$vm_name" \
        --arg vm_size "$vm_size" \
        --arg vm_os "$vm_os" \
        --arg operation "$operation" \
        --arg result "$result" \
        --argjson result_time $result_time \
        --arg unit "seconds" \
        --arg message "$message" \
        --arg disk_name "$disk_name" \
        --arg disk_size "$(echo $disk_info | jq -r '.[0].Size')" \
        --arg disk_type "$(echo $disk_info | jq -r '.[0].StorageType')" \
        --arg run_id "$run_id" \
        '{
            "timestamp": $timestamp,
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
                "time": $result_time,
                "unit": $unit,
                "message": $message
            },
            "disk_info": {
                "disk_name": $disk_name,
                "disk_size": $disk_size,
                "disk_type": $disk_type
            },
            "run_id": $run_id,
            "run_url": $url"
        }')

        echo $json_template
    )
}

_catch()
{
    echo "CATCH"
    local json_template=$(jq -n \
    --arg timestamp "$timestamp" \
    --arg cloud "$cloud" \
    --arg region "$region" \
    --arg vm_name "$vm_name" \
    --arg vm_size "$vm_size" \
    --arg vm_os "$vm_os" \
    --arg operation "$operation" \
    --arg result "$result" \
    --argjson result_time $result_time \
    --arg unit "seconds" \
    --arg message "$message" \
    --arg disk_name "$disk_name" \
    --arg disk_size "$(echo $disk_info | jq -r '.[0].Size')" \
    --arg disk_type "$(echo $disk_info | jq -r '.[0].StorageType')" \
    --arg run_id "$run_id" \
    '{
        "timestamp": "",
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
            "message": "Unknwon error"
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

# function to collect results
collect_results() {
    local result_dir=$1
    local result_file=$2
    # merge all JSON files into one file
    cat $result_dir/*.json > $result_dir/$result_file
    echo "Results collected and merged into json file"
}
