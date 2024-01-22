#!/bin/bash

source ./modules/bash/utils.sh

run_jmeter() {
  local ingress_ip_address=$1
  local egress_ip_address=$2
  local privatekey_path=$3
  local jmeter_file_dest=$4
  local jmeter_properties=$5
  local jmeter_result_file=$6
  local jmeter_aggregate_file=$7
  local jmeter_log_file=$8
  local result_dir=$9

  # sleep 5m
  jmeterCommand="jmeter -n -t ${jmeter_file_dest}/https_test.jmx -f -p ${jmeter_file_dest}/jmeter.properties -j ${jmeter_file_dest}/${jmeter_log_file}.log ${jmeter_properties}"
  echo "Run test command: $jmeterCommand"
  run_ssh $privatekey_path ubuntu $egress_ip_address 2222 "$jmeterCommand"

  aggregateCommand="java -jar /opt/jmeter/lib/cmdrunner-2.2.jar --tool Reporter --generate-csv ${jmeter_file_dest}/${jmeter_aggregate_file}.csv --input-jtl ${jmeter_file_dest}/${jmeter_result_file}.csv --plugin-type AggregateReport"
  echo "Run aggregate command: $aggregateCommand"
  run_ssh $privatekey_path ubuntu $egress_ip_address 2222 "$aggregateCommand"

  echo "Copy result files to local"
  run_scp_local $privatekey_path ubuntu $egress_ip_address 2222 "${jmeter_file_dest}/${jmeter_aggregate_file}.csv" "${result_dir}/${jmeter_aggregate_file}.csv"
  run_scp_local $privatekey_path ubuntu $egress_ip_address 2222 "${jmeter_file_dest}/${jmeter_result_file}.csv" "${result_dir}/${jmeter_result_file}.csv"
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