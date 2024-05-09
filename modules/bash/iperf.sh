#!/bin/bash

source ./modules/bash/utils.sh

check_iperf_setup() {
  local ip_address=$1
  local version=$2
  local privatekey_path=$3

  echo "Check iperf setup"
  if [ "$version" = "3" ]; then
    command="iperf3 --version"
  else
    command="iperf"
  fi

  echo "run_ssh $privatekey_path ubuntu $ip_address $command"
  run_ssh $privatekey_path ubuntu $ip_address 2222 "$command"
  if [ "$?" -ne 0 ]; then
    echo "Command $command failed with exit code $?"
    exit 1
  fi
}

run_iperf3() {
  local ingress_ip_address=$1
  local egress_ip_address=$2
  local user_name=$3
  local ssh_port=$4
  local privatekey_path=$5
  local result_dir=$6
  local protocol=$7
  local bandwidth=$8
  local iperf_properties=$9


  mkdir -p $result_dir
  echo "Run evaluation on $egress_ip_address with user name $user_name and ssh key $privatekey_path and result path $result_dir"

  local command="iperf3 $iperf_properties --json"

  port=20001
  if [ "$protocol" = "udp" ]; then
    port=20002
  fi

  echo "Wait for 1 minutes before running"
  sleep 60
  local fullCommand="$command --port $port"
  echo "Run iperf3 command: $fullCommand"
  run_ssh $privatekey_path $user_name $egress_ip_address $ssh_port "$fullCommand" > $result_dir/iperf3-${protocol}-${bandwidth}.json
}

run_iperf2_draft_run(){
  local destination_ip_address=$1
  local client_public_ip_address=$2
  local protocol=$3
  local wait_time=$4
  local privatekey_path=$5
  local server_public_ip_address=$6
  local result_dir=$7
  local jumpbox_public_ip_address=${8:-''}

  if [ -n "$jumpbox_public_ip_address" ]; then
    echo "Jumpbox public IP address is set to $jumpbox_public_ip_address, will test via jumpbox"
  fi
  
  echo "Wait for $wait_time seconds before running all tests"
  sleep $wait_time

  echo "Perform a draft run to warm up the vm"
  local command="iperf --enhancedreports --client $destination_ip_address --format m --time 30"
  if [ "$protocol" = "udp" ]; then
    command="$command --udp --port 20002"
  else
   command="$command --port 20001"
  fi

  if [ -z "$jumpbox_public_ip_address" ]; then
    echo "run_ssh $privatekey_path ubuntu $client_public_ip_address $command"
    run_ssh $privatekey_path ubuntu $client_public_ip_address 2222 "$command"
  else
    echo "run_ssh_via_jumpbox $privatekey_path ubuntu $jumpbox_public_ip_address $client_public_ip_address $command"
    run_ssh_via_jumpbox $privatekey_path ubuntu $jumpbox_public_ip_address $client_public_ip_address 2222 "$command"
  fi
  echo "Completed draft run"
}

run_iperf2() {
  local destination_ip_address=$1
  local client_public_ip_address=$2
  local protocol=$3
  local wait_time=$4
  local privatekey_path=$5
  local server_public_ip_address=$6
  local result_dir=$7
  local iperf_properties=$8
  local bandwidth=$9
  local jumpbox_public_ip_address=${10:-''}

  if [ -n "$jumpbox_public_ip_address" ]; then
    echo "Jumpbox public IP address is set to $jumpbox_public_ip_address, will test via jumpbox"
  fi

  local command="iperf --enhancedreports $iperf_properties --format m"

  if [ "$protocol" = "udp" ]; then
    port=20002
  else
    port=20001
  fi
  command="$command --port $port"

  echo "Wait for 1 minutes before running"
  sleep 60

  if [ -z "$jumpbox_public_ip_address" ]; then
    echo "run_ssh $privatekey_path ubuntu $client_public_ip_address $command"
    run_ssh $privatekey_path ubuntu $client_public_ip_address 2222 "$command" > $result_dir/iperf2-${protocol}-${bandwidth}.log
  else
    echo "run_ssh_via_jumpbox $privatekey_path ubuntu $jumpbox_public_ip_address $client_public_ip_address $command"
    run_ssh_via_jumpbox $privatekey_path ubuntu $jumpbox_public_ip_address $client_public_ip_address 2222 "$command" > $result_dir/iperf2-${protocol}-${bandwidth}.log
  fi
  # for debug
  echo ======== iperf2-${protocol}-${bandwidth}.log ========
  cat $result_dir/iperf2-${protocol}-${bandwidth}.log
}

collect_result_iperf3() {
  local result_dir=$1
  local egress_ip_address=$2
  local ingress_ip_address=$3
  local cloud_info=$4
  local run_id=$5
  local protocol=$6
  local bandwidth=$7

  touch $result_dir/results.json

  iperf_result="$result_dir/iperf3-${protocol}-${bandwidth}.json"
  cat $iperf_result
  iperf_info=$(python3 ./modules/python/iperf3/parser.py $protocol $iperf_result)

  if echo "$iperf_info" | jq '.timestamp' > /dev/null; then
    timestamp=$(echo "$iperf_info" | jq -r '.timestamp')
  else
    timestamp="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
  fi

  data=$(jq --null-input \
    --arg timestamp "$timestamp" \
    --arg metric "$protocol" \
    --arg target_bw "$bandwidth" \
    --arg unit "Mbits/sec" \
    --arg iperf_info "$iperf_info" \
    --arg cloud_info "$cloud_info" \
    --arg egress_ip "$egress_ip_address" \
    --arg ingress_ip "$ingress_ip_address" \
    --arg run_id "$run_id" \
    '{timestamp: $timestamp, metric: $metric, target_bandwidth: $target_bw, unit: $unit, iperf_info: $iperf_info, cloud_info: $cloud_info, egress_ip: $egress_ip, ingress_ip: $ingress_ip, run_id: $run_id}')

  echo $data >> $result_dir/results.json
}

collect_result_iperf2() {
  local result_dir=$1
  local egress_ip_address=$2
  local ingress_ip_address=$3
  local cloud_info=$4
  local run_id=$5
  local run_url=$6
  local protocol=$7
  local bandwidth=$8

  touch $result_dir/results.json

	iperf_result="$result_dir/iperf2-${protocol}-${bandwidth}.log"
  echo "Check iPerf log file:"
  cat $iperf_result
  iperf_info=$(python3 ./modules/python/iperf2/parser.py $protocol $iperf_result)
  echo "iPerf result: $iperf_info"

  client_cpu_info=$(cat $result_dir/client-lscpu.json | jq -c .)
  server_cpu_info=$(cat $result_dir/server-lscpu.json | jq -c .)
  os_info=$(jq --null-input \
    --arg client_cpu_info "$client_cpu_info" \
    --arg server_cpu_info "$server_cpu_info" \
    '{client_cpu_info: $client_cpu_info, server_cpu_info: $server_cpu_info}')

  data=$(jq --null-input \
    --arg timestamp "$(date -u +"%Y-%m-%dT%H:%M:%SZ")" \
    --arg metric "$protocol" \
    --arg target_bw "$bandwidth" \
    --arg unit "Mbits/sec" \
    --arg iperf_info "$iperf_info" \
    --arg os_info "$os_info" \
    --arg cloud_info "$cloud_info" \
    --arg egress_ip "$egress_ip_address" \
    --arg ingress_ip "$ingress_ip_address" \
    --arg run_id "$run_id" \
    --arg run_url "$run_url" \
    '{timestamp: $timestamp, metric: $metric, target_bandwidth: $target_bw, unit: $unit, iperf_info: $iperf_info, os_info: $os_info, cloud_info: $cloud_info, egress_ip: $egress_ip, ingress_ip: $ingress_ip, run_id: $run_id, run_url: $run_url}')

  echo $data >> $result_dir/results.json
}
