#!/bin/bash

# set column names for JSON output
operation_column="operation"
disk_name_column="disk_name"
time_column="time"
result_column="result"

# set Kusto database connection details
kusto_cluster="your_kusto_cluster"
kusto_database="your_kusto_database"
kusto_table="your_kusto_table"

#function to initialize tests
init_tests() {
    # create tmp directory if it does not exist
    mkdir -p tmp

    # get vm name and disk names
    vm_name=$(get_vm_instance_by_name $run_id $role)
    disk_names=($(get_disk_instance_by_name $run_id $scenario_type $scenario_name))

    echo "Tests initialized. VM name: $vm_name, Disk names: ${disk_names[@]}"
}

#function to run disk test
run_disk_test() {
    local disk_name=$1

    echo "Running tests for disk: $disk_name"
    start_time=$(date +%s)
    echo "Executing attach operation for disk: $disk_name"
    attach_result=$(attach_disk $vm_name $disk_name $resource_group)
    end_time=$(date +%s)
    if [ "$attach_result" == "success" ]; then
        attach_time=$(($end_time - $start_time))
    else
        attach_time=-1
    fi
    attach_output="{\"$operation_column\": \"attach\", \"$disk_name_column\": \"$disk_name\", \"$time_column\": $attach_time, \"$time_unit_column\": \"seconds\", \"$result_column\": \"$attach_result\"}"
    attach_filename="tmp/$(cat /dev/urandom | tr -dc 'a-zA-Z0-9' | fold -w 32 | head -n 1).json"
    echo $attach_output > $attach_filename
    echo "Attach operation result: $attach_result, time: $attach_time seconds"

    if [ "$attach_result" == "success" ]; then
        start_time=$(date +%s)
        echo "Executing detach operation for disk: $disk_name"
        detach_result=$(detach_disk $vm_name $disk_name $resource_group)
        end_time=$(date +%s)
        if [ "$detach_result" == "success" ]; then
            detach_time=$(($end_time - $start_time))
        else
            detach_time=-1
        fi
        detach_output="{\"$operation_column\": \"detach\", \"$disk_name_column\": \"$disk_name\", \"$time_column\": $detach_time, \"$time_unit_column\": \"seconds\", \"$result_column\": \"$detach_result\"}"
        detach_filename="tmp/$(cat /dev/urandom | tr -dc 'a-zA-Z0-9' | fold -w 32 | head -n 1).json"
        echo $detach_output > $detach_filename
        echo "Detach operation result: $detach_result, time: $detach_time seconds"
    fi
}

#function to run tests
run_tests() {
    for disk_name in "${disk_names[@]}"; do
        run_disk_test $disk_name &
    done
    wait
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
    cat tmp/*.json > json_results
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
run_id=$1
role=$2
scenario_type=$3
scenario_name=$4
resource_group=$5
cloud=$6

source "./$cloud/utils.sh"

#init_tests
#run_tests
#collect_results
upload_results $ACCOUNT_NAME $ACCOUNT_KEY $scenario_type/$scenario_name v1 json_results