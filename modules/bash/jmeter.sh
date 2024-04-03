#!/bin/bash

source ./modules/bash/utils.sh

run_jmeter() {
  local egress_ip_address=$1
  local privatekey_path=$2
  local protocol=$3
  local concurrency=$4
  local user_properties=$5
  local jmeter_file_dest=$6
  local result_dir=$7

  sleep 1m
  jmeterCommand="jmeter -n -t ${jmeter_file_dest}/https_test.jmx -f -S ${jmeter_file_dest}/jmeter.properties -j ${jmeter_file_dest}/jmeter-${protocol}-${concurrency}.log -l ${jmeter_file_dest}/result-${protocol}-${concurrency}.csv ${user_properties}"
  echo "Run test command: $jmeterCommand"
  run_ssh $privatekey_path ubuntu $egress_ip_address 2222 "$jmeterCommand"

  aggregateCommand="java -jar /opt/jmeter/lib/cmdrunner-2.2.jar --tool Reporter --generate-csv ${jmeter_file_dest}/aggregate-${protocol}-${concurrency}.csv --input-jtl ${jmeter_file_dest}/result-${protocol}-${concurrency}.csv --plugin-type AggregateReport"
  echo "Run aggregate command: $aggregateCommand"
  run_ssh $privatekey_path ubuntu $egress_ip_address 2222 "$aggregateCommand"

  echo "Copy result files to local"
  run_scp_local $privatekey_path ubuntu $egress_ip_address 2222 "${jmeter_file_dest}/aggregate-${protocol}-${concurrency}.csv" "${result_dir}/aggregate-${protocol}-${concurrency}.csv"
  run_scp_local $privatekey_path ubuntu $egress_ip_address 2222 "${jmeter_file_dest}/result-${protocol}-${concurrency}.csv" "${result_dir}/result-${protocol}-${concurrency}.csv"
}

collect_result_jmeter()
{
  local protocol=$1
  local concurrency=$2
  local result_dir=$3
  local run_id=$4
  local run_url=$5
  local cloud_info=$6
  local test_dir=$7

  echo "Collect result for $protocol with $concurrency concurrency"
  python3 $test_dir/modules/python/jmeter/parser.py "${result_dir}/result-${protocol}-${concurrency}.csv" "aggregate" true "${result_dir}/aggregate-${protocol}-${concurrency}.csv"
  result=$(python3 $test_dir/modules/python/jmeter/parser.py "${result_dir}/result-${protocol}-${concurrency}.csv" "aggregate" false)

  data=$(jq --null-input \
    --arg timestamp "$(date -u +"%Y-%m-%dT%H:%M:%SZ")" \
    --arg protocol "$protocol" \
    --arg concurrency "$concurrency" \
    --arg cloud_info "$cloud_info" \
    --arg result "$result" \
    --arg run_id "$run_id" \
    --arg run_url "$run_url" \
    '{timestamp: $timestamp, protocol: $protocol, cloud_info: $cloud_info, result: $result, run_id: $run_id, run_url: $run_url, concurrency: $concurrency}')

  touch $result_dir/results.json
  echo $data >> $result_dir/results.json
}