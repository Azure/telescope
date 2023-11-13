#!/bin/bash

source ./modules/bash/azure.sh

run_eof() {
  local resource_group=$1
  local vmss=$2
  local vm=$3
  local tag=$4
  local iteration=$5
  local limit=$6
  local timeout=$7
  local ingress_ip_address=$8
  local scripts_dir=$9

  echo "Running server side"
  azure_vmss_run_command $resource_group $vmss "@${scripts_dir}/run-server.sh" "$tag $timeout"

  echo "Running client side"
  azure_vm_run_command $resource_group $vm "@${scripts_dir}/run-client.sh" "$tag $ingress_ip_address $iteration $limit"

  echo "Checking results"
  finished=false
  while [ $finished = false ]
  do
    result=$(azure_vm_run_command $resource_group $vm "grep times /home/adminuser/client_build/logs.txt" "")
    message=$(echo $result | jq .value[0].message)
    echo -e $message | tail -n 10
    if [[ "$message" == *"$iteration"* ]]; then
      echo "Finished"
      finished=true
    else
      echo "Waiting for test to finish"
      sleep 60
    fi
  done
}

collect_result_eof() {
  local iteration=$1
  local tag=$2
  local resource_group=$3
  local vm=$4
  local location=$5
  local machine_type=$6
  local ingress_ip_address=$7
  local egress_ip_address=$8
  local run_link=$9
  local result_file=${10}

  echo "Collect EOF result"
  result=$(azure_vm_run_command $resource_group $vm "grep EOF /home/adminuser/client_build/logs.txt" "")
  message=$(echo $result | jq .value[0].message)
  echo -e $message

  count=$(echo -e $message | grep EOF | wc -l)
  echo "EOF count: $count"

  data=$(jq --null-input \
    --arg metric "EOF" \
    --arg value "$count" \
    --arg unit "times" \
    --arg timestamp "$(date -u +"%Y-%m-%dT%H:%M:%SZ")" \
    --arg run_url "$run_link" \
    --arg resource_group "$resource_group" \
    --arg location "$location" \
    --arg vm_size "$machine_type" \
    --arg egress_ip "$egress_ip_address" \
    --arg ingress_ip "$ingress_ip_address" \
    --arg iteration "$iteration" \
    --arg release_tag "$tag" \
    --arg message "$message" \
    '{metric: $metric, value: $value, unit: $unit, timestamp: $timestamp, run_url: $run_url, resource_group: $resource_group, location: $location, vm_size: $vm_size, egress_ip: $egress_ip, ingress_ip: $ingress_ip, iteration: $iteration, release_tag: $release_tag, message: $message}')

  echo "Saving result to ${result_file}"
  echo $data >> "${result_file}"
}
