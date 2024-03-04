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

  local protocolList=("tcp" "udp")
  local bandwidthList=(100 1000 2000 4000)

  mkdir -p $result_dir
  echo "Run evaluation on $egress_ip_address with user name $user_name and ssh key $privatekey_path and result path $result_dir"

  for protocol in "${protocolList[@]}"
  do
    for bandwidth in "${bandwidthList[@]}"
    do
      local command="iperf3 --client $ingress_ip_address --time 60 --json"

      port=20001
      if [ "$protocol" = "udp" ]; then
        command="$command --udp"
        port=20002
      fi

      echo "Wait for 1 minutes before running"
      sleep 60
      local fullCommand="$command --bandwidth ${bandwidth}M --port $port"
      echo "Run iperf3 command: $fullCommand"
      run_ssh $privatekey_path $user_name $egress_ip_address $ssh_port "$fullCommand" > $result_dir/iperf3-${protocol}-${bandwidth}.json
    done
  done
}

run_iperf2() {
  local destination_ip_address=$1
  local client_public_ip_address=$2
  local thread_mode=$3
  local protocol=$4
  local run_time=$5
  local wait_time=$6
  local privatekey_path=$7
  local server_public_ip_address=$8
  local result_dir=$9
  local jumpbox_public_ip_address=${10:-''}

  if [ -n "$jumpbox_public_ip_address" ]; then
    echo "Jumpbox public IP address is set to $jumpbox_public_ip_address, will test via jumpbox"
  fi

  local bandwidthList=(100 1000 2000 4000)

  echo "Wait for $wait_time seconds before running all tests"
  sleep $wait_time

  echo "Perform a draft run to warm up the vm"
  if [ "$protocol" = "udp" ]; then
    command="iperf --enhancedreports --client $destination_ip_address --format m --time 30 --udp --port 20002"
  else
    command="iperf --enhancedreports --client $destination_ip_address --format m --time 30 --port 20001"
  fi
  if [ -z "$jumpbox_public_ip_address" ]; then
    echo "run_ssh $privatekey_path ubuntu $client_public_ip_address $command"
    run_ssh $privatekey_path ubuntu $client_public_ip_address 2222 "$command"
  else
    echo "run_ssh_via_jumpbox $privatekey_path ubuntu $jumpbox_public_ip_address $client_public_ip_address $command"
    run_ssh_via_jumpbox $privatekey_path ubuntu $jumpbox_public_ip_address $client_public_ip_address 2222 "$command"
  fi

  for bandwidth in "${bandwidthList[@]}"
  do
    local command="iperf --enhancedreports --client $destination_ip_address --format m --time $run_time"

    if [ "$protocol" = "udp" ]; then
      port=20002
      command="$command --udp --port $port"
    else
      port=20001
      command="$command --port $port"
    fi

    local parallel=1
    local run_bandwidth=$bandwidth
    if [ "$thread_mode" = "multi" ]; then
      parallel=$(echo "$bandwidth / 1000" | bc)
      if [ "$parallel" -eq 0 ]; then
        parallel=1
      else
        run_bandwidth=1000
      fi
    fi

    command="$command --parallel $parallel --bandwidth ${run_bandwidth}M"

    echo "Wait for 1 minutes before running"
    sleep 60

    if [ -z "$jumpbox_public_ip_address" ]; then
      echo "run_ssh $privatekey_path ubuntu $client_public_ip_address $command"
      run_ssh $privatekey_path ubuntu $client_public_ip_address 2222 "$command" > $result_dir/iperf2-${protocol}-${bandwidth}.log
    else
      echo "run_ssh_via_jumpbox $privatekey_path ubuntu $jumpbox_public_ip_address $client_public_ip_address $command"
      run_ssh_via_jumpbox $privatekey_path ubuntu $jumpbox_public_ip_address $client_public_ip_address 2222 "$command" > $result_dir/iperf2-${protocol}-${bandwidth}.log
      # for debug
      echo ======== iperf2-${protocol}-${bandwidth}.log ========
      cat $result_dir/iperf2-${protocol}-${bandwidth}.log
    fi
  done
}

collect_result_iperf3() {
  local result_dir=$1
  local egress_ip_address=$2
  local ingress_ip_address=$3
  local cloud_info=$4
  local run_id=$5

  touch $result_dir/results.json

  local protocolList=("tcp" "udp")
  local bandwidthList=(100 1000 2000 4000)

  for protocol in "${protocolList[@]}"
  do
    for bandwidth in "${bandwidthList[@]}"
    do
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
    done
  done
}

collect_result_iperf2() {
  local result_dir=$1
  local egress_ip_address=$2
  local ingress_ip_address=$3
  local cloud_info=$4
  local run_id=$5
  local run_url=$6

  touch $result_dir/results.json

  local protocolList=("tcp" "udp")
  local bandwidthList=(100 1000 2000 4000)

  for protocol in "${protocolList[@]}"
  do
    for bandwidth in "${bandwidthList[@]}"
    do
      iperf_result="$result_dir/iperf2-${protocol}-${bandwidth}.log"
      cat $iperf_result
      iperf_info=$(python3 ./modules/python/iperf2/parser.py $protocol $iperf_result)

      os_info="{}"

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
    done
  done
}
