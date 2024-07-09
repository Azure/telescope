#!/bin/bash

source ./modules/bash/utils.sh

run_sockperf() {
    local egress_ip_address=$1
    local user_name=$2
    local ssh_port=$3
    local privatekey_path=$4
    local result_dir=$5
    local protocol=$6
    local sockperf_properties=$7

    mkdir -p $result_dir
    echo "Run evaluation on $egress_ip_address with user name $user_name at $ssh_port and ssh key $privatekey_path and result path $result_dir"

    # sockperf ping-pong -i 10.2.1.122 -p 20004 -t 20 --tcp --pps=max --full-rtt
    local command="sockperf $sockperf_properties --pps=max --full-rtt"

    echo "Wait for 1 minutes before running"
    sleep 60
    echo "Run sockperf command: $command"
    run_ssh $privatekey_path $user_name $egress_ip_address $ssh_port "$command" > $result_dir/sockperf-${protocol}.log
}

collect_result_sockperf() {
  local result_dir=$1
  local egress_ip_address=$2
  local ingress_ip_address=$3
  local cloud_info=$4
  local run_id=$5
  local run_url=$6
  local protocol=$7

  touch $result_dir/results.json

  sockperf_result="$result_dir/sockperf-${protocol}.log"
  cat $sockperf_result
  sockperf_info=$(python3 ./modules/python/sockperf/parser.py $protocol $sockperf_result)
  timestamp="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"

  data=$(jq --null-input \
    --arg timestamp "$timestamp" \
    --arg metric "$protocol" \
    --arg unit "usec" \
    --arg sockperf_info "$sockperf_info" \
    --arg cloud_info "$cloud_info" \
    --arg egress_ip "$egress_ip_address" \
    --arg ingress_ip "$ingress_ip_address" \
    --arg run_id "$run_id" \
    --arg run_url "$run_url" \
    '{timestamp: $timestamp, metric: $metric, unit: $unit, sockperf_info: $sockperf_info, cloud_info: $cloud_info, egress_ip: $egress_ip, ingress_ip: $ingress_ip, run_id: $run_id, run_url: $run_url}')

  echo $data >> $result_dir/results.json
}
