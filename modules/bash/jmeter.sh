#!/bin/bash

source ./modules/bash/utils.sh

check_jmeter_setup() {
  local egress_ip_address=$1
  local privatekey_path=$2

  echo "Check jmeter setup"
  commands=("java -version" "jmeter -v" "ls /opt/jmeter/lib/cmdrunner-2.2.jar" "ls /opt/jmeter/lib/ext/jmeter-plugins-manager-1.7.jar" "ls /opt/jmeter/bin/JMeterPluginsCMD.sh" "ls /opt/jmeter/lib/ext/jmeter-plugins-synthesis-2.2.jar")
  for command in "${commands[@]}"
  do
    echo "run_ssh $privatekey_path ubuntu $egress_ip_address $command"
    run_ssh $privatekey_path ubuntu $egress_ip_address 2222 "$command"
    if [ "$?" -ne 0 ]; then
      echo "Command $command failed with exit code $?"
      exit 1
    fi
  done
}

run_jmeter() {
  local ingress_ip_address=$1
  local egress_ip_address=$2
  local scenario_type=$3
  local scenario_name=$4
  local privatekey_path=$5
  local protocol=$6
  local port=$7
  local concurrency=$8
  local loop=$9

  local jmeter_file_source=./scenarios/${scenario_type}/${scenario_name}/bash-scripts
  local jmeter_file_dest=/tmp/jmeter

  echo "Make temp directory"
  run_ssh $privatekey_path ubuntu $egress_ip_address 2222 "mkdir -p $jmeter_file_dest"
  echo "Copy properties and jmx files"
  run_scp_remote $privatekey_path ubuntu $egress_ip_address "${jmeter_file_source}/jmeter.properties" "${jmeter_file_dest}/jmeter.properties"
  run_scp_remote $privatekey_path ubuntu $egress_ip_address "${jmeter_file_source}/https_test.jmx" "${jmeter_file_dest}/https_test.jmx"
  run_scp_remote $privatekey_path ubuntu $egress_ip_address "${jmeter_file_source}/alias.csv" "${jmeter_file_dest}/alias.csv"

  sleep 5m
  jmeterCommand="jmeter -n -t ${jmeter_file_dest}/https_test.jmx -f -p ${jmeter_file_dest}/jmeter.properties -Jprotocol=${protocol} -Jport=${port} -Jip_address=${ingress_ip_address} -Jthread_num=${concurrency} -Jloop_count=${loop} -Jresult_file_name=${jmeter_file_dest}/result-${protocol}-${concurrency} -j ${jmeter_file_dest}/jmeter-${protocol}-${concurrency}.log"
  echo "Run test command: $jmeterCommand"
  run_ssh $privatekey_path ubuntu $egress_ip_address 2222 "$jmeterCommand"

  aggregateCommand="java -jar /opt/jmeter/lib/cmdrunner-2.2.jar --tool Reporter --generate-csv ${jmeter_file_dest}/aggregate-${protocol}-${concurrency}.csv --input-jtl ${jmeter_file_dest}/result-${protocol}-${concurrency}.csv --plugin-type AggregateReport"
  echo "Run aggregate command: $aggregateCommand"
  run_ssh $privatekey_path ubuntu $egress_ip_address 2222 "$aggregateCommand"

  echo "Copy result files to local"
  run_scp_local $privatekey_path ubuntu $egress_ip_address "${jmeter_file_dest}/aggregate-${protocol}-${concurrency}.csv" "/tmp/aggregate-${protocol}-${concurrency}.csv"
  run_scp_local $privatekey_path ubuntu $egress_ip_address "${jmeter_file_dest}/result-${protocol}-${concurrency}.csv" "/tmp/result-${protocol}-${concurrency}.csv"
}

collect_result_jmeter()
{
  local protocol=$1
  local concurrency=$2
  local result_dir=$3
  local run_id=$4
  local run_url=$5

  echo "Collect result for $protocol with $concurrency concurrency"
  result=$(cat "/tmp/aggregate-${protocol}-${concurrency}.csv" | python3 -c 'import csv, json, sys; print(json.dumps([dict(r) for r in csv.DictReader(sys.stdin)]))')

  head -n 1 "/tmp/result-${protocol}-${concurrency}.csv" | cut -d "," -f 4,5 > "/tmp/error-${protocol}-${concurrency}.csv"
  tail -n +2 "/tmp/result-${protocol}-${concurrency}.csv" | grep -v OK | cut -d "," -f 4,5 | sort -u >> "/tmp/error-${protocol}-${concurrency}.csv"
  count=$(cat "/tmp/error-${protocol}-${concurrency}.csv" | wc -l)
  error=""
  if [ "$count" -gt 1 ]; then
    error=$(cat "/tmp/error-${protocol}-${concurrency}.csv" | python3 -c 'import csv, json, sys; print(json.dumps([dict(r) for r in csv.DictReader(sys.stdin)]))')
  fi

  data=$(jq --null-input \
    --arg timestamp "$(date -u +"%Y-%m-%dT%H:%M:%SZ")" \
    --arg protocol "$protocol" \
    --arg concurrency "$concurrency" \
    --arg cloud_info "$cloud_info" \
    --arg result "$result" \
    --arg error "$error" \
    --arg run_id "$run_id" \
    --arg run_url "$run_url" \
    '{timestamp: $timestamp, protocol: $protocol, cloud_info: $cloud_info, result: $result, error: $error, run_id: $run_id, run_url: $run_url, concurrency: $concurrency}')

  touch $result_dir/results.json
  echo $data >> $result_dir/results.json
}