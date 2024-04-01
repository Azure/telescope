#!/bin/bash

# function to measure attach operation
measure_attach() {
    local disk_name=$1

    start_time=$(date +%s)
    attach_result=$(attach_disk $vm_name $disk_name $resource_group)
    end_time=$(date +%s)
    if [ "$attach_result" == "success" ]; then
        attach_time=$(($end_time - $start_time))
    else
        attach_time=-1
    fi

    # Get the disk size using the Azure CLI
    disk_size=$(az disk show --name $disk_name --resource-group $resource_group --query "diskSizeGb" --output tsv)

    attach_output='{
        "timestamp": "'$(date)'",
        "region": "'$region'",
        "operation_info": {
            "operation": "attach",
            "result": "'$attach_result'",
            "time": '$attach_time',
            "unit": "seconds"
        },
        "vm_info": {
            "vm_name": "'$vm_name'",
            "size": "'$vm_size'",
            "os": "'$vm_os'"
        },
        "disk_info": {
            "disk_name": "'$disk_name'",
            "disk_size": "'$disk_size'"
        },
        "run_id": "'$run_id'"
    }'

    echo $attach_output
}

# function to measure detach operation
measure_detach() {
    local disk_name=$1

    start_time=$(date +%s)
    detach_result=$(detach_disk $vm_name $disk_name $resource_group)
    end_time=$(date +%s)
    if [ "$detach_result" == "success" ]; then
        detach_time=$(($end_time - $start_time))
    else
        detach_time=-1
    fi

    # Get the disk size using the Azure CLI
    disk_size=$(az disk show --name $disk_name --resource-group $resource_group --query "diskSizeGb" --output tsv)

    detach_output='{
        "timestamp": "'$(date)'",
        "region": "'$region'",
        "operation_info": {
            "operation": "detach",
            "result": "'$detach_result'",
            "time": '$detach_time',
            "unit": "seconds"
        },
        "vm_info": {
            "vm_name": "'$vm_name'",
            "size": "'$vm_size'",
            "os": "'$vm_os'"
        },
        "disk_info": {
            "disk_name": "'$disk_name'",
            "disk_size": "'$disk_size'"
        },
        "run_id": "'$run_id'"
    }'
    echo $detach_output
}

#function to run disk test
run_alternate_tests() {
    local disk_name=$1

    attach_output=$(measure_attach $disk_name)
    attach_filename="$result_dir/$(cat /dev/urandom | tr -dc 'a-zA-Z0-9' | fold -w 32 | head -n 1).json"
    echo $attach_output > $attach_filename

    if [ "$(echo $attach_output | jq -r .$result_column)" == "success" ]; then
        detach_output=$(measure_detach $disk_name)
        detach_filename="$result_dir/$(cat /dev/urandom | tr -dc 'a-zA-Z0-9' | fold -w 32 | head -n 1).json"
        echo $detach_output > $detach_filename
    fi
}

#function to run tests
run_tests() {
    for index in "${!disk_names[@]}"; do
        disk_name="${disk_names[$index]}"
        attach_output=$(measure_attach $disk_name)
        echo $result_dir
        attach_filename="$result_dir/$(cat /dev/urandom | tr -dc 'a-zA-Z0-9' | fold -w 32 | head -n 1).json"
        echo $attach_filename
        echo $attach_output > "$attach_filename"
    done

    for index in "${!disk_names[@]}"; do
        disk_name="${disk_names[$index]}"
        if [ "$(az disk show --name $disk_name --resource-group $resource_group --query "diskState" --output tsv)" == "Attached" ]; then
            detach_output=$(measure_detach $disk_name)
            detach_filename="$result_dir/$(cat /dev/urandom | tr -dc 'a-zA-Z0-9' | fold -w 32 | head -n 1).json"
            echo $detach_output > "$detach_filename"
        fi
    done
}


#function to execute tests
execute()
{
    run_id=$1
    scenario_type=$2
    scenario_name=$3
    export result_dir=$4
    export resource_group=$run_id

    # get vm name and disk names
    vm_name=$(get_vm_instance_by_name $run_id)
    disk_names=($(get_disk_instance_by_name $run_id $scenario_type $scenario_name))

    # get VM operating system and size
    vm_os=$(az vm show --name $vm_name --resource-group $resource_group --query "storageProfile.osDisk.osType" --output tsv)
    vm_size=$(az vm show --name $vm_name --resource-group $resource_group --query "hardwareProfile.vmSize" --output tsv)

    region=$(az group show --name $resource_group --query "location" --output tsv)

    echo "Tests initialized. VM name: $vm_name, Disk names: ${disk_names[@]}"

    # Export variables
    export vm_name
    export disk_names
    export vm_os
    export vm_size
    export region

    run_tests
}

#function to collect results
collect_results()  {
    local result_dir=$1
    local result_file=$2
    # merge all JSON files into one file
    cat $result_dir/*.json > $result_dir/$result_file
    echo "Results collected and merged into json file"
}

#function to upload results
upload_results() {
    local storage_account_name=$1
    local account_key=$2
    local container_name=$3
    local filename=$4
    local source_filename=$5

    # upload file to Azure storage blob
    az storage blob upload --account-name $storage_account_name --account-key $account_key --container-name $container_name --name $filename --file $source_filename

    echo "Results uploaded to Azure storage blob"
}