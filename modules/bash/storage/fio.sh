source ./modules/bash/utils.sh

set -e

if $DEBUG; then
    set -x
fi

check_fio_setup_on_remote_vm() {
  local ip_address=$1
  local privatekey_path=$2

  echo "Check fio setup"
  local command="fio --version"

  echo "run_ssh $privatekey_path ubuntu $ip_address $command"
  run_ssh $privatekey_path ubuntu $ip_address "$command"
  if [ "$?" -ne 0 ]; then
    echo "Command $command failed with exit code $?"
    exit 1
  fi
}

run_fio_on_remote_vm() {
  local egress_ip_address=$1
  local privatekey_path=$2
  local mount_point=$3
  local result_dir=$4

  mkdir -p $result_dir

  local methods=("randread" "randrw" "read" "rw")

  echo "Run fio"

  set +x # disable debug output because it will mess up the output of fio
  for method in "${methods[@]}"
  do
    local command="sudo fio --name=benchtest --size=800m --filename=/${mount_point}/${method} --direct=1 --rw=$method --ioengine=libaio --bs=4k --iodepth=16 --numjobs=8 --time_based --runtime=60 --output-format=json --group_reporting"
    echo "Run command: $command"
    run_ssh $privatekey_path ubuntu $egress_ip_address "$command" | tee $result_dir/fio-${method}.log
  done
  if $DEBUG; then # re-enable debug output if DEBUG is set
    set -x
  fi
}


collect_result_fio() {
  local result_dir=$1

  echo "collecting fio results from $result_dir/fio-*.log into $result_dir/result.json"

  run_link="https://github.com/azure-management-and-platforms/cloud-network-evaluator/actions/runs/${RUN_ID}/job/${JOB_ID}"

  local methods=("randread" "randrw" "read" "rw")

  # TODO(@guwe): add pricing

  for method in "${methods[@]}"
  do
    result="$result_dir/fio-${method}.log"
    echo "========= collecting ${result} ==========="
    cat $result

    read_iops_avg=$(cat $result | jq '.jobs[0].read.iops_mean')
    read_bw_avg=$(cat $result | jq '.jobs[0].read.bw_mean')
    write_iops_avg=$(cat $result | jq '.jobs[0].write.iops_mean')
    write_bw_avg=$(cat $result | jq '.jobs[0].write.bw_mean')

    data=$(jq --null-input \
      --arg timestamp "$(date -u +"%Y-%m-%dT%H:%M:%SZ")" \
      --arg method "$method" \
      --arg location "$REGION" \
      --arg vm_size "$MACHINE_TYPE" \
      --arg run_url "$run_link" \
      --arg cloud "$CLOUD" \
      --arg data_disk_type "$DATA_DISK_TYPE" \
      --arg data_disk_size "$DATA_DISK_SIZE_GB" \
      --arg data_disk_tier "$DATA_DISK_TIER" \
      --arg data_disk_iops_rw "$DATA_DISK_IOPS_READ_WRITE" \
      --arg data_disk_iops_r "$DATA_DISK_IOPS_READ_ONLY" \
      --arg data_disk_mbps_rw "$DATA_DISK_MBPS_READ_WRITE" \
      --arg data_disk_mbps_r "$DATA_DISK_MBPS_READ_ONLY" \
      --arg data_disk_price_per_month "$DATA_DISK_PRICE_PER_MONTH" \
      --arg read_iops_avg "$read_iops_avg" \
      --arg read_bw_avg "$read_bw_avg" \
      --arg write_iops_avg "$write_iops_avg" \
      --arg write_bw_avg "$write_bw_avg" \
      '{timestamp: $timestamp, method: $method, location: $location, vm_size: $vm_size, run_url: $run_url, cloud: $cloud, data_disk_type: $data_disk_type, data_disk_size: $data_disk_size, data_disk_tier: $data_disk_tier, data_disk_iops_rw: $data_disk_iops_rw, data_disk_iops_r: $data_disk_iops_r, data_disk_mbps_rw: $data_disk_mbps_rw, data_disk_mbps_r: $data_disk_mbps_r, data_disk_price_per_month: $data_disk_price_per_month, read_iops_avg: $read_iops_avg, read_bw_avg: $read_bw_avg, write_iops_avg: $write_iops_avg, write_bw_avg: $write_bw_avg}')

    echo $data >> $result_dir/results.json
  done
}