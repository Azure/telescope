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

  local command="sudo df -hT $mount_point"
  run_ssh $privatekey_path ubuntu $egress_ip_address "$command"

  # prepare files for fio, when the method is/has read, we need to create a file before that
  local file_size="1G"
  local file_path="/${mount_point}/benchtest"
  local command="sudo dd if=/dev/zero of=$file_path bs=$file_size count=1"
  echo "Run command: $command"
  run_ssh $privatekey_path ubuntu $egress_ip_address "$command"
  local command="sudo ls -l $file_path"
  echo "Run command: $command"
  run_ssh $privatekey_path ubuntu $egress_ip_address "$command"
  sleep 30 # wait to clean any potential throttle / cache

  local methods=("randread" "randrw" "read" "rw")
  # temporary disable rw for case common_s3_bucket, we have problem with rw right now, error:
  # fio: io_u error on file //tmp/mnt/blob/benchtest: Transport endpoint is not connected: write offset=24621056, buflen=4096
  # fio: io_u error on file //tmp/mnt/blob/benchtest: Software caused connection abort: read offset=24285184, buflen=4096
  # fio: io_u error on file //tmp/mnt/blob/benchtest: Software caused connection abort: write offset=23252992, buflen=4096
  # fio: io_u error on file //tmp/mnt/blob/benchtest: Transport endpoint is not connected: write offset=25751552, buflen=4096
  # fio: io_u error on file //tmp/mnt/blob/benchtest: Transport endpoint is not connected: write offset=24768512, buflen=4096
  # fio: io_u error on file //tmp/mnt/blob/benchtest: Transport endpoint is not connected: write offset=24227840, buflen=4096
  # fio: io_u error on file //tmp/mnt/blob/benchtest: Transport endpoint is not connected: write offset=24907776, buflen=4096
  # fio: io_u error on file //tmp/mnt/blob/benchtest: Transport endpoint is not connected: write offset=25550848, buflen=4096
  # fio: pid=14694, err=107/file:io_u.c:1787, func=io_u error, error=Transport endpoint is not connected
  # fio: pid=14701, err=103/file:io_u.c:1787, func=io_u error, error=Software caused connection abort
  # fio: pid=14695, err=103/file:io_u.c:1787, func=io_u error, error=Software caused connection abort
  # fio: pid=14698, err=107/file:io_u.c:1787, func=io_u error, error=Transport endpoint is not connected
  # fio: pid=14700, err=107/file:io_u.c:1787, func=io_u error, error=Transport endpoint is not connected
  # fio: pid=14697, err=107/file:io_u.c:1787, func=io_u error, error=Transport endpoint is not connected
  # fio: pid=14699, err=107/file:io_u.c:1787, func=io_u error, error=Transport endpoint is not connected
  # fio: pid=14696, err=107/file:io_u.c:1787, func=io_u error, error=Transport endpoint is not connected
  if [ "$CASE_NAME" == "common_s3_bucket" ]; then
    methods=("randread" "randrw" "read")
  fi

  echo "Run fio"

  set +x # disable debug output because it will mess up the output of fio
  for method in "${methods[@]}"
  do
    local command="sudo fio --name=benchtest --size=800m --filename=$file_path --direct=1 --rw=$method --ioengine=libaio --bs=4k --iodepth=16 --numjobs=8 --time_based --runtime=60 --output-format=json --group_reporting"
    echo "Run command: $command"
    run_ssh $privatekey_path ubuntu $egress_ip_address "$command" | tee $result_dir/fio-${method}.log
    sleep 30 # wait to clean any potential throttle / cache
  done
  if $DEBUG; then # re-enable debug output if DEBUG is set
    set -x
  fi
}


collect_result_disk_fio() {
  local result_dir=$1
  local run_link=$2

  echo "collecting fio results from $result_dir/fio-*.log into $result_dir/result.json"

  local methods=("randread" "randrw" "read" "rw")

  # TODO(@guwe): add pricing
  DATA_DISK_PRICE_PER_MONTH="${DATA_DISK_PRICE_PER_MONTH:=0}"

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
      --arg case_name "$CASE_NAME" \
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
      '{
        timestamp: $timestamp,
        method: $method,
        location: $location,
        vm_size: $vm_size,
        run_url: $run_url,
        cloud: $cloud,
        case_name: $case_name,
        data_disk_type: $data_disk_type,
        data_disk_size: $data_disk_size,
        data_disk_tier: $data_disk_tier,
        data_disk_iops_rw: $data_disk_iops_rw,
        data_disk_iops_r: $data_disk_iops_r,
        data_disk_mbps_rw: $data_disk_mbps_rw,
        data_disk_mbps_r: $data_disk_mbps_r,
        data_disk_price_per_month: $data_disk_price_per_month,
        read_iops_avg: $read_iops_avg,
        read_bw_avg: $read_bw_avg,
        write_iops_avg: $write_iops_avg,
        write_bw_avg: $write_bw_avg
      }')

    echo $data >> $result_dir/results.json
  done
}

collect_result_blob_fio() {
  local result_dir=$1
  local run_link=$2

  echo "collecting fio results from $result_dir/fio-*.log into $result_dir/result.json"

  local methods=("randread" "randrw" "read" "rw")
  # temporary disable rw for case common_s3_bucket, we have problem with rw right now
  if [ "$CASE_NAME" == "common_s3_bucket" ]; then
    methods=("randread" "randrw" "read")
  fi

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
      --arg case_name "$CASE_NAME" \
      --arg storage_tier "$STORAGE_TIER" \
      --arg storage_kind "$STORAGE_KIND" \
      --arg storage_replication "$STORAGE_REPLICATION" \
      --arg read_iops_avg "$read_iops_avg" \
      --arg read_bw_avg "$read_bw_avg" \
      --arg write_iops_avg "$write_iops_avg" \
      --arg write_bw_avg "$write_bw_avg" \
      '{
        timestamp: $timestamp,
        method: $method,
        location: $location,
        vm_size: $vm_size,
        run_url: $run_url,
        cloud: $cloud,
        case_name: $case_name,
        storage_tier: $storage_tier,
        storage_kind: $storage_kind,
        storage_replication: $storage_replication,
        read_iops_avg: $read_iops_avg,
        read_bw_avg: $read_bw_avg,
        write_iops_avg: $write_iops_avg,
        write_bw_avg: $write_bw_avg
      }')

    echo $data >> $result_dir/results.json
  done
}

collect_result_fileshare_fio() {
  local result_dir=$1
  local run_link=$2

  echo "collecting small file results from $result_dir/worldpress.log into $result_dir/result.json"
  local worldpress_log="$result_dir/worldpress.log"
  cat $worldpress_log
  small_file_rw=$(cat $worldpress_log | grep real | awk '{print $2}')
  if [ -z "$small_file_rw" ]; then
    echo "small_file_rw is empty, set to 0"
    small_file_rw="0"
  fi

  echo "collecting fio results from $result_dir/fio-*.log into $result_dir/result.json"

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
      --arg case_name "$CASE_NAME" \
      --arg storage_tier "$STORAGE_TIER" \
      --arg storage_kind "$STORAGE_KIND" \
      --arg storage_replication "$STORAGE_REPLICATION" \
      --arg storage_share_quota "$STORAGE_SHARE_QUOTA" \
      --arg storage_share_enabled_protocol "$STORAGE_SHARE_ENABLED_PROTOCOL" \
      --arg read_iops_avg "$read_iops_avg" \
      --arg read_bw_avg "$read_bw_avg" \
      --arg write_iops_avg "$write_iops_avg" \
      --arg write_bw_avg "$write_bw_avg" \
      --arg small_file_rw "$small_file_rw" \
      '{
        timestamp: $timestamp,
        method: $method,
        location: $location,
        vm_size: $vm_size,
        run_url: $run_url,
        cloud: $cloud,
        case_name: $case_name,
        storage_tier: $storage_tier,
        storage_kind: $storage_kind,
        storage_replication: $storage_replication,
        storage_share_quota: $storage_share_quota,
        storage_share_enabled_protocol: $storage_share_enabled_protocol,
        read_iops_avg: $read_iops_avg,
        read_bw_avg: $read_bw_avg,
        write_iops_avg: $write_iops_avg,
        write_bw_avg: $write_bw_avg,
        small_file_rw: $small_file_rw
      }')

    echo $data >> $result_dir/results.json
  done
}