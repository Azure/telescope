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
    run_ssh $privatekey_path ubuntu $egress_ip_address "$command"
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

  local jmeter_file_source=./scenarios/${scenario_type}/${scenario_name}/bash-scripts
  local jmeter_file_dest=/tmp/jmeter

  echo "Make temp directory"
  run_ssh $privatekey_path ubuntu $egress_ip_address "mkdir -p $jmeter_file_dest"
  echo "Copy properties and jmx files"
  run_scp_remote $privatekey_path ubuntu $egress_ip_address "${jmeter_file_source}/jmeter.properties" "${jmeter_file_dest}/jmeter.properties"
  run_scp_remote $privatekey_path ubuntu $egress_ip_address "${jmeter_file_source}/https_test.jmx" "${jmeter_file_dest}/https_test.jmx"
  run_scp_remote $privatekey_path ubuntu $egress_ip_address "${jmeter_file_source}/alias.csv" "${jmeter_file_dest}/alias.csv"

  protocol=("http" "https")
  port=(80 443)
  concurrency=(100 500 1000)
  loop=(200 100 50)

  echo "Run evaluation"
  for i in "${!protocol[@]}"
  do
    for j in "${!concurrency[@]}"
    do
      echo "Wait for 5 minutes before running"
      sleep 5m

      jmeterCommand="jmeter -n -t ${jmeter_file_dest}/https_test.jmx -f -S "${jmeter_file_dest}/jmeter.properties" -Jprotocol=${protocol[i]} -Jport=${port[i]} -Jip_address=${ingress_ip_address} -Jthread_num=${concurrency[j]} -Jloop_count=${loop[j]} -Jresult_file_name=${jmeter_file_dest}/result-${protocol[i]}-${concurrency[j]} -j ${jmeter_file_dest}/jmeter-${protocol[i]}-${concurrency[j]}.log"
      echo "Run test command: $jmeterCommand"
      run_ssh $privatekey_path ubuntu $egress_ip_address "$jmeterCommand"


      run_ssh $privatekey_path ubuntu $egress_ip_address "dir "


      aggregateCommand="java -jar /opt/jmeter/lib/cmdrunner-2.2.jar --tool Reporter --generate-csv ${jmeter_file_dest}/aggregate-${protocol[i]}-${concurrency[j]}.csv --input-jtl ${jmeter_file_dest}/result-${protocol[i]}-${concurrency[j]}.csv --plugin-type AggregateReport"
      echo "Run aggregate command: $aggregateCommand"
      run_ssh $privatekey_path ubuntu $egress_ip_address "$aggregateCommand"

      echo "Copy result files to local"
      run_scp_local $privatekey_path ubuntu $egress_ip_address "${jmeter_file_dest}/aggregate-${protocol[i]}-${concurrency[j]}.csv" "/tmp/aggregate-${protocol[i]}-${concurrency[j]}.csv"
      run_scp_local $privatekey_path ubuntu $egress_ip_address "${jmeter_file_dest}/result-${protocol[i]}-${concurrency[j]}.csv" "/tmp/result-${protocol[i]}-${concurrency[j]}.csv"
    done
  done
}

run_jmeter_appgateway_lb()
{
  local ingress_ip_address=$1
  local egress_ip_address=$2  
  local scenario_type=$3
  local scenario_name=$4
  local privatekey_path=$5

  local jmeter_file_source=./scenarios/${scenario_type}/${scenario_name}/bash-scripts
  local jmeter_file_dest=/tmp/jmeter

  echo "Make temp directory"
  run_ssh $privatekey_path ubuntu $egress_ip_address "mkdir -p $jmeter_file_dest"
  echo "Copy properties and jmx files"
  run_scp_remote $privatekey_path ubuntu $egress_ip_address "${jmeter_file_source}/jmeter.properties" "${jmeter_file_dest}/jmeter.properties"
  run_scp_remote $privatekey_path ubuntu $egress_ip_address "${jmeter_file_source}/https_test.jmx" "${jmeter_file_dest}/https_test.jmx"
  protocol=("http" "https")
  for i in "${!protocol[@]}"
  do

    jmeterCommand="jmeter -n -t ${jmeter_file_dest}/https_test.jmx -f -l "${jmeter_file_dest}/results_${protocol[i]}.csv" -Jbackend_type=lb -Jbackend_protocol=${protocol[i]} -Jip_address="${ingress_ip_address}" -S "${jmeter_file_dest}/jmeter.properties""
    echo "Run test command: $jmeterCommand"
    run_ssh $privatekey_path ubuntu $egress_ip_address "$jmeterCommand"

    aggregateCommand="java -jar /opt/jmeter/lib/cmdrunner-2.2.jar --tool Reporter --generate-csv ${jmeter_file_dest}/aggregate-${protocol[i]}.csv --input-jtl ${jmeter_file_dest}/results_${protocol[i]}.csv --plugin-type AggregateReport"
    echo "Run aggregate command: $aggregateCommand"
    run_ssh $privatekey_path ubuntu $egress_ip_address "$aggregateCommand"

    echo "Copy result files to local"
    run_scp_local $privatekey_path ubuntu $egress_ip_address "${jmeter_file_dest}/aggregate-${protocol[i]}.csv" "aggregate-${protocol[i]}.csv"
  done
}

collect_result_jmeter() {
  local result_dir=$1
  local result_file=$2
  local run_link=$3
  local cloud=$4
  local region=$5
  local resource_group=$6
  local machine_type=$7
  local extra_info=$8

  create_file $result_dir $result_file

  protocolList=("http" "https")
  concurrencyList=(100 500 1000)

  for protocol in "${protocolList[@]}"
  do
    for concurrency in "${concurrencyList[@]}"
    do
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
        --arg metric "$protocol" \
        --arg concurrency "$concurrency" \
        --arg result "$result" \
        --arg error "$error" \
        --arg cloud "$cloud" \
        --arg location "$region" \
        --arg resource_group "$resource_group" \
        --arg vm_size "$machine_type" \
        --arg run_url "$run_link" \
        --arg extra_info "$extra_info" \
        '{timestamp: $timestamp, metric: $metric, concurrency: $concurrency, result: $result, error: $error, cloud: $cloud, resource_group: $resource_group, location: $location, vm_size: $vm_size, extra_info: $extra_info, run_url: $run_url}')

      echo $data >> $result_file
    done
  done
}