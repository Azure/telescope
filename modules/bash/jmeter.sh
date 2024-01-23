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

  echo "Collect result for $protocol with $concurrency concurrency"
  result=$(cat "${result_dir}/aggregate-${protocol}-${concurrency}.csv" | python3 -c 'import csv, json, sys; print(json.dumps([dict(r) for r in csv.DictReader(sys.stdin)]))')

  head -n 1 "${result_dir}/result-${protocol}-${concurrency}.csv" | cut -d "," -f 4,5 > "${result_dir}/error-${protocol}-${concurrency}.csv"
  tail -n +2 "${result_dir}/result-${protocol}-${concurrency}.csv" | grep -v OK | cut -d "," -f 4,5 | sort -u >> "${result_dir}/error-${protocol}-${concurrency}.csv"
  count=$(cat "${result_dir}/error-${protocol}-${concurrency}.csv" | wc -l)
  error=""
  if [ "$count" -gt 1 ]; then
    error=$(cat "${result_dir}/error-${protocol}-${concurrency}.csv" | python3 -c 'import csv, json, sys; print(json.dumps([dict(r) for r in csv.DictReader(sys.stdin)]))')
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