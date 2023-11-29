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
  run_ssh $privatekey_path ubuntu $ip_address "$command"
  if [ "$?" -ne 0 ]; then
    echo "Command $command failed with exit code $?"
    exit 1
  fi
}

run_iperf3() {
  local ingress_ip_address=$1
  local egress_ip_address=$2
  local privatekey_path=$3

  local protocolList=("tcp" "udp")
  local bandwidthList=(100 1000 2000 4000)
  
  echo "Run evaluation"
  for protocol in "${protocolList[@]}"
  do
    for bandwidth in "${bandwidthList[@]}"
    do
      local command="iperf3 --client $ingress_ip_address --time 60 --json"

      if [ "$protocol" = "udp" ]; then
        command="$command --udp"
      fi

      local fullCommand=""
      local parallel=$(echo "$bandwidth / 1000" | bc)
      if [ "$parallel" -gt 1 ]; then
        command="$command --bandwidth 1000M"
        for i in $(seq 1 $parallel)
        do
          fullCommand+="$command --port 2000$i &> /tmp/${protocol}-${bandwidth}-thread$i.json & "
        done
        echo "Run iperf3 command: $fullCommand"
        run_ssh $privatekey_path ubuntu $egress_ip_address "$fullCommand" 
        
        while true
        do
          count=$(run_ssh $privatekey_path ubuntu $egress_ip_address "ps -ef | grep iperf3 | grep -v grep | wc -l")
          if [ "$count" -eq 0 ]; then
            break
          fi
          echo "Waiting for $count iperf3 processes to finish"
          sleep 5
        done

        echo "Merging results"
        run_ssh $privatekey_path ubuntu $egress_ip_address "jq -s '.' /tmp/${protocol}-${bandwidth}-thread*.json" > /tmp/iperf3-${protocol}-${bandwidth}.json
      else 
        fullCommand="$command --bandwidth ${bandwidth}M --port 20001"
        echo "Run iperf3 command: $fullCommand"
        run_ssh $privatekey_path ubuntu $egress_ip_address "$fullCommand" > /tmp/iperf3-${protocol}-${bandwidth}.json
      fi
    done
  done
}

run_iperf2_helper() {
  local destination_ip_address=$1
  local client_public_ip_address=$2
  local thread_mode=$3
  local protocol=$4
  local privatekey_path=$5
  local server_public_ip_address=$6
  local result_dir=$7

  local bandwidthList=(100 1000 2000 4000)

  echo "Wait for 4 minutes before running all tests"
  sleep 240

  for bandwidth in "${bandwidthList[@]}"
  do
    local command="iperf --enhancedreports --client $destination_ip_address --format m --time 10"
    
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

    echo "fetch_proc_net $server_public_ip_address $privatekey_path $port $protocol"
    fetch_proc_net $server_public_ip_address $privatekey_path $port $protocol > $result_dir/proc-net-${protocol}-${bandwidth}.log &
    PID1=$!

    echo "run_ssh $privatekey_path ubuntu $client_public_ip_address $command"
    run_ssh $privatekey_path ubuntu $client_public_ip_address "$command" > $result_dir/iperf2-${protocol}-${bandwidth}.log &
    PID2=$!
    wait $PID1 $PID2
  done
}

run_iperf2() {
  local destination_ip_address=$1
  local client_public_ip_address=$2
  local tcp_mode=$3
  local udp_mode=$4
  local privatekey_path=$5
  local server_public_ip_address=$6
  local result_dir=$7

  mkdir -p $result_dir
  run_iperf2_helper $destination_ip_address $client_public_ip_address $tcp_mode "tcp" $privatekey_path $server_public_ip_address $result_dir
  run_iperf2_helper $destination_ip_address $client_public_ip_address $udp_mode "udp" $privatekey_path $server_public_ip_address $result_dir
}

publish_result_iperf3() {
  local blob_subfolder_name=$1
  local job_id=$2

  publish_common $job_id $run_id
  
  local protocolList=("tcp" "udp")
  local bandwidthList=(100 1000 2000 4000)
  
  for protocol in "${protocolList[@]}"
  do
    for bandwidth in "${bandwidthList[@]}"
    do
      result="/tmp/iperf3-${protocol}-${bandwidth}.json"
      if [ "$bandwidth" -gt 1000 ]; then
        start_info=$(jq '[ .[].start ]' $result)
        end_info=$(jq '[ .[].end ]' $result)
      else
        start_info=$(jq '[ .start ]' $result)
        end_info=$(jq '[ .end ]' $result)
      fi
      
      data=$(jq --null-input \
        --arg timestamp "$(date -u +"%Y-%m-%dT%H:%M:%SZ")" \
        --arg metric "$protocol" \
        --arg target_bw "$bandwidth" \
        --arg unit "Mbits/sec" \
        --arg start_info "$start_info" \
        --arg end_info "$end_info" \
        --arg resource_group "" \
        --arg location "$REGION" \
        --arg vm_size "$MACHINE_TYPE" \
        --arg egress_ip "$EGRESS_IP_ADDRESS" \
        --arg ingress_ip "$INGRESS_IP_ADDRESS" \
        --arg run_url "$run_link" \
        --arg extra_info "$extra_info" \
        '{timestamp: $timestamp, metric: $metric, target_bandwidth: $target_bw, unit: $unit, start_info: $start_info, end_info: $end_info, resource_group: $resource_group, location: $location, vm_size: $vm_size, egress_ip: $egress_ip, ingress_ip: $ingress_ip, extra_info: $extra_info, run_url: $run_url}')

      echo $data >> /tmp/${job_id}/result.json
    done
  done

  az_blob_upload /tmp/${job_id}/result.json ${job_id}.json "${blob_subfolder_name}"
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
      iperf_info=$(python3 ./modules/python/parse-iperf2.py $protocol $iperf_result)

      proc_net_result="$result_dir/proc-net-${protocol}-${bandwidth}.log"
      read proc_net_rx_queue proc_net_drops < $proc_net_result
      os_info=$(jq --null-input \
        --arg pnrq "$proc_net_rx_queue" \
        --arg pnd "$proc_net_drops" \
        '{"proc_net_rx_queue": $pnrq, "proc_net_drops": $pnd}')

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