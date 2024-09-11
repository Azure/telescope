#!/bin/bash

run_deployment() {
    yaml_file=$1
    pod_count=$2
    result_file=$3

    echo "Running batch jobs"
    start_time=$(date +%s)
    echo "Start time: $start_time"
    kubectl apply -f $yaml_file
    
    # Wait for all pods to be running
    while true; do
        pods_num=$(kubectl get pods | grep scalejobs | grep -c Running)
        if [ $pods_num -eq $pod_count ]; then
            break
        fi
        echo "Waiting for all pods to be running, current pods count: $pods_num"
        sleep 5
    done
    end_time=$(date +%s)
    echo "End time: $end_time"

    run_time=$((end_time-start_time))
    echo "Total run time in seconds: $run_time"

    echo "Verify all pods are running"
    kubectl get pods
    echo "Verfiy all nodes are running"
    kubectl get nodes

    data=$(jq -n \
        --arg start_time "$start_time" \
        --arg end_time "$end_time" \
        --arg run_time "$run_time" \
        '{start_time: $start_time, end_time: $end_time, run_time: $run_time}')
    echo $data > $result_file
}

calculate_request_resource() {
    node_name=$1
    node_count=$2
    pod_count=$3
    input_file=$4
    output_file=$5

    # Extract allocatable CPU and memory for the specified node
    allocatable_cpu=$(kubectl get node $node_name -o jsonpath='{.status.allocatable.cpu}')
    allocatable_memory=$(kubectl get node $node_name -o jsonpath='{.status.allocatable.memory}')

    echo "Allocatable CPU for node $node_name: $allocatable_cpu"
    echo "Allocatable Memory for node $node_name: $allocatable_memory"

    # Separate CPU value and unit
    if [[ "$allocatable_cpu" =~ ^([0-9]+)([a-z]*)$ ]]; then
        cpu_value="${BASH_REMATCH[1]}"
        cpu_unit="${BASH_REMATCH[2]}"
    fi

    # Separate memory value and unit
    if [[ "$allocatable_memory" =~ ^([0-9]+)([a-zA-Z]*)$ ]]; then
        memory_value="${BASH_REMATCH[1]}"
        memory_unit="${BASH_REMATCH[2]}"
    fi

    echo "CPU value: $cpu_value"
    echo "Memory value: $memory_value"

    # Calculate request cpu and memory for each pod
    cpu_request=$(((cpu_value - 400) * node_count / pod_count))
    memory_request=$((memory_value * node_count / pod_count))
    
    echo "Total number of nodes: $node_count, total number of pods: $pod_count"
    echo "CPU request for each pod: $cpu_request$cpu_unit"
    echo "Memory request for each pod: $memory_request$memory_unit"

    sed "s/##CPUperJob##/$cpu_request$cpu_unit/g" $input_file > $output_file
    echo >> $output_file
}

generate_jobs() {
    job_count=$1
    input_file=$2
    output_file=$3
    for ((i=1; i<=job_count; i++)); do
        if [ $i -eq 1 ]; then
            cat $input_file | sed "s/\$ITEM/$i/" | sed "39s/ /---/"> $output_file
        else
            cat $input_file | sed "s/\$ITEM/$i/" | sed "39s/ /---/">> $output_file
        fi
    done
}

execute_scale_up() {
    node_name=$1
    node_count=$2
    pod_count=$3
    job_template=$4
    job_resource_template=$5
    jobs_file=$6
    result_file=$7

    calculate_request_resource $node_name $node_count $pod_count $job_template $job_resource_template
    generate_jobs $pod_count $job_resource_template $jobs_file
    run_deployment $jobs_file $pod_count $result_file
}

collect_scale_up() {
    data_file=$1
    cloud_info=$2
    scale_feature=$3
    pod_count=$4
    node_count=$5
    run_id=$6
    run_url=$7
    result_file=$8

    data=$(cat $data_file)
    result=$(jq -n \
        --arg timestamp "$(date -u +"%Y-%m-%dT%H:%M:%SZ")" \
        --arg scale_feature "$scale_feature" \
        --arg pod_count "$pod_count" \
        --arg node_count "$node_count" \
        --arg data "$data" \
        --arg cloud_info "$cloud_info" \
        --arg run_id "$run_id" \
        --arg run_url "$run_url" \
        '{
            timestamp: $timestamp, 
            scale_feature: $scale_feature,
            pod_count: $pod_count,
            node_count: $node_count,
            data: $data,
            cloud_info: $cloud_info,
            run_id: $run_id,
            run_url: $run_url
        }')
    echo $result > $result_file
}