#!/bin/bash

# set column names for JSON output
operation_column="operation"
disk_name_column="disk_name"
time_column="time"
result_column="result"
time_unit_column="unit"
timestamp_column="timestamp"

# set Kusto database connection details
kusto_cluster="your_kusto_cluster"
kusto_database="your_kusto_database"
kusto_table="your_kusto_table"

#function to initialize tests
init_tests() {
    local run_id=$1
    local scenario_type=$2
    local scenario_name=$3

    # create tmp directory if it does not exist
    mkdir -p tmp

    # get vm name and disk names
    vm_name=$(get_vm_instance_by_name $run_id)
    disk_names=($(get_disk_instance_by_name $run_id $scenario_type $scenario_name))

    # get VM operating system and size
    vm_os=$(az vm show --name $vm_name --resource-group $resource_group --query "storageProfile.osDisk.osType" --output tsv)
    vm_size=$(az vm show --name $vm_name --resource-group $resource_group --query "hardwareProfile.vmSize" --output tsv)

    # retrieve disk sizes
    disk_sizes=()
    for disk_name in "${disk_names[@]}"; do
        disk_size=$(az disk show --name $disk_name --resource-group $resource_group --query "diskSizeGb" --output tsv)
        disk_sizes+=($disk_size)
    done

    echo "Tests initialized. VM name: $vm_name, Disk names: ${disk_names[@]}"
}

# function to measure attach operation
measure_attach() {
    local disk_name=$1

    echo "Executing attach operation for disk: $disk_name"  > /dev/tty
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

    echo "Executing detach operation for disk: $disk_name"  > /dev/tty
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
run_disk_test() {
    local disk_name=$1
    local disk_size=$2

    echo "Running tests for disk: $disk_name"
    attach_output=$(measure_attach $disk_name $disk_size)
    attach_filename="tmp/$(cat /dev/urandom | tr -dc 'a-zA-Z0-9' | fold -w 32 | head -n 1).json"
    echo $attach_output > $attach_filename
    echo "Attach operation result: $(echo $attach_output | jq -r .$result_column), time: $(echo $attach_output | jq -r .$time_column) seconds"

    if [ "$(echo $attach_output | jq -r .$result_column)" == "success" ]; then
        detach_output=$(measure_detach $disk_name $disk_size)
        detach_filename="tmp/$(cat /dev/urandom | tr -dc 'a-zA-Z0-9' | fold -w 32 | head -n 1).json"
        echo $detach_output > $detach_filename
        echo "Detach operation result: $(echo $detach_output | jq -r .$result_column), time: $(echo $detach_output | jq -r .$time_column) seconds"
    fi
}

#function to run tests
run_tests() {
    for index in "${!disk_names[@]}"; do
        disk_name="${disk_names[$index]}"
        run_disk_test $disk_name &
        wait
    done
    wait
}


#function to execute tests
execute()
{
    run_id=$1
    scenario_type=$2
    scenario_name=$3
    resource_group=$run_id

    # create tmp directory if it does not exist
    mkdir -p tmp

    # get vm name and disk names
    vm_name=$(get_vm_instance_by_name $run_id)
    disk_names=($(get_disk_instance_by_name $run_id $scenario_type $scenario_name))

    # get VM operating system and size
    vm_os=$(az vm show --name $vm_name --resource-group $resource_group --query "storageProfile.osDisk.osType" --output tsv)
    vm_size=$(az vm show --name $vm_name --resource-group $resource_group --query "hardwareProfile.vmSize" --output tsv)

    echo "Tests initialized. VM name: $vm_name, Disk names: ${disk_names[@]}"

    # Export variables
    export vm_name
    export disk_names
    export vm_os
    export vm_size

    #init_tests $run_id $scenario_type $scenario_name
    run_tests
}

#function to collect results
collect_results() {
    for filename in tmp/*.json; do
        az kusto ingest inline into table $kusto_table --cluster $kusto_cluster --database $kusto_database --data $(cat $filename)
    done
    echo "Results collected and uploaded to Kusto database"
}

#function to collect results
collect_results() {
    # merge all JSON files into one file
    cat tmp/*.json > json_results.json
    echo "Results collected and merged into json_results file"
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

#main script
#run_id=$1
#scenario_type=$2
#scenario_name=$3
#cloud=$4
#resource_group=$run_id

#source "./$cloud/utils.sh"

#init_tests
#run_tests
#collect_results
#upload_results $ACCOUNT_NAME $ACCOUNT_KEY $scenario_type/$scenario_name v1 json_results