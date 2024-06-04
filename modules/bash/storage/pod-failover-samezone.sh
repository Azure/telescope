#!/bin/bash
source ./modules/bash/utils.sh

azure_run_pod_failover_samezone_test() {
  local resource_group=$1
  local aks_name=$2
  local test_times=$3
  local result_dir=$4

  mkdir -p $result_dir

  az aks get-credentials -n $aks_name -g $resource_group
  curl -skSL https://raw.githubusercontent.com/Azure/kubernetes-volume-drivers/master/test/pod_failover_test_azure.sh | bash -s $test_times $result_dir/pod-failover-samezone-${test_times}-times.txt -- 
}

aws_run_pod_failover_samezone_test() {
  local region=$1
  local eks_name=$2
  local test_times=$3
  local result_dir=$4

  mkdir -p $result_dir

  aws eks --region $region update-kubeconfig --name $eks_name
  curl -skSL https://raw.githubusercontent.com/Azure/kubernetes-volume-drivers/master/test/pod_failover_test_aws.sh | bash -s $test_times $result_dir/pod-failover-samezone-${test_times}-times.txt -- 
}

collect_result_pod_failover_samezone() {
  local result_dir=$1
  local run_link=$2
  local test_times=$3

  echo "collecting pod failover on same zone test results from $result_dir/pod-failover-samezone-${test_times}-times.txt into $result_dir/results.json"

  result="$result_dir/pod-failover-samezone-${test_times}-times.txt"
  echo "========= collecting ${result} ==========="
  cat $result

  for i in $(seq $test_times)
  do
  datetime=$(cat $result | grep "test $i:" | cut -c 1-20)
  pod_failover_time=$(cat $result | grep "test $i:" | awk '{print $4}')
  echo $pod_failover_time
  data=$(jq --null-input \
    --arg timestamp "$datetime" \
    --arg location "$REGION" \
    --arg vm_size "$MACHINE_TYPE" \
    --arg run_url "$run_link" \
    --arg cloud "$CLOUD" \
    --arg case_name "$CASE_NAME" \
    --arg pod_failover_time "$pod_failover_time" \
    '{
      timestamp: $timestamp,
      location: $location,
      vm_size: $vm_size,
      run_url: $run_url,
      cloud: $cloud,
      case_name: $case_name,
      pod_failover_time: $pod_failover_time
    }')

  echo $data >> $result_dir/results.json
  done
}
