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
  run_ssh $privatekey_path ubuntu $ip_address 2222 "$command"
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
  local bs=$5
  local iodepth=$6
  local method=$7
  local runtime=$8
  local storage_name=$9

  mkdir -p $result_dir

  local command="sudo df -hT $mount_point"
  run_ssh $privatekey_path ubuntu $egress_ip_address 2222 "$command"

  local file_size=$((10*1024*1024*1024))

  local file_path="${mount_point}/benchtest"

  echo "Run fio"

  set +x # disable debug output because it will mess up the output of fio

  local command="sudo fio --name=benchtest --size=$file_size --filename=$file_path --direct=1 --rw=$method --ioengine=libaio --bs=$bs --iodepth=$iodepth --time_based --runtime=$runtime --output-format=json"

  # prepare files for the actual run using fio option --create_only=1
  setup_command="${command} --create_only=1"
  echo "Run command: $setup_command"
  run_ssh $privatekey_path ubuntu $egress_ip_address 2222 "$setup_command"
  sleep 30 # wait to clean any potential throttle / cache

  # execute the actual run for metrics collection
  echo "Run command: $command"
  start_time=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
  run_ssh $privatekey_path ubuntu $egress_ip_address 2222 "$command" | tee $result_dir/fio.log
  end_time=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

  metadata_json="{\"BlockSize\": \"$bs\", \"IoDepth\": \"$iodepth\", \"Operation\": \"$method\", \"FileSize\": \"$file_size\",  \"StorageName\": \"$storage_name\", \"StartTime\": \"$start_time\", \"EndTime\": \"$end_time\"}"
  echo "$metadata_json" > $result_dir/metadata.log

  if $DEBUG; then # re-enable debug output if DEBUG is set
    set -x
  fi
}

run_fio_on_pod() {
  local pod_name=$1
  local mount_point=$2
  local result_dir=$3
  local bs=$4
  local iodepth=$5
  local method=$6
  local runtime=$7
  local storage_name=$8

  mkdir -p $result_dir

  local file_size=$((10*1024*1024*1024))

  local file_path="${mount_point}/benchtest"

  echo "Run fio"

  set +x # disable debug output because it will mess up the output of fio

  local command="fio --name=benchtest --size=$file_size --filename=$file_path --direct=1 --rw=$method --ioengine=libaio --bs=$bs --iodepth=$iodepth --time_based --runtime=$runtime --output-format=json"

  # prepare files for the actual run using fio option --create_only=1
  setup_command="${command} --create_only=1"
  echo "Run setup command: $setup_command"
  run_kubectl_exec $pod_name fio "$setup_command"
  sleep 30 # wait to clean any potential throttle / cache

  # execute the actual run for metrics collection
  echo "Run command: $command"
  start_time=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
  run_kubectl_exec $pod_name fio "$command" | tee $result_dir/fio.log
  end_time=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

  metadata_json="{\"BlockSize\": \"$bs\", \"IoDepth\": \"$iodepth\", \"Operation\": \"$method\", \"FileSize\": \"$file_size\", \"StorageName\": \"$storage_name\", \"StartTime\": \"$start_time\", \"EndTime\": \"$end_time\"}"
  echo "$metadata_json" > $result_dir/metadata.log

  if $DEBUG; then # re-enable debug output if DEBUG is set
    set -x
  fi
}

run_fio_fileopenclose_multiple_pods_setup() {
  local pod_name=$1
  local mount_point=$2
  local result_dir=$3
  local file_name_prefix=$4
  local num_files=$5
  local num_jobs_parallel=$6
  local runtime=$7

  local target_directory="${mount_point}/${pod_name}"
  local num_files_per_job=$((num_files / num_jobs_parallel))

  mkdir_command="mkdir -p $target_directory"
  run_kubectl_exec $pod_name fio "$mkdir_command"
  mkdir -p $result_dir

  echo "Run fio"

  set +x # disable debug output because it will mess up the output of fio

  local command="fio --name=$file_name_prefix --filesize=4096 --directory=$target_directory --thread=1 --readwrite=rw --nrfiles=$num_files_per_job --ioengine=fileopenclose --numjobs=$num_jobs_parallel --time_based --runtime=$runtime --openfiles=1 --group_report --output-format=json"

  # prepare files for the actual run using fio option --create_only=1
  setup_command="${command} --create_only=1"
  echo "Run setup command: $setup_command"
  run_kubectl_exec $pod_name fio "$setup_command" &

  if $DEBUG; then # re-enable debug output if DEBUG is set
    set -x
  fi
}

wait_fio_done() {
  local pod_name=$1
  local result_dir=$2

  local command="ps"
  run_kubectl_exec $pod_name fio "$command"
  echo "Polling for setup command"

  # while run_kubectl_exec $pod_name fio "$command" | grep -q 'fio'; do echo "Still running fio"; sleep 60; done
  while true; do
    output=$(run_kubectl_exec $pod_name fio "$command")
    if [ $? -ne 0 ]; then
      echo "Error executing command in pod $pod_name. Retrying in 60 seconds..."
      sleep 60
      continue
    fi

    if ! echo "$output" | grep -q 'fio'; then
      echo "fio process not found in pod $pod_name. Exiting loop."
      kubectl logs $pod_name > $result_dir/log-${pod_name}.log
      kubectl get events --field-selector involvedObject.name=$pod_name > $result_dir/events-${pod_name}.log
      break
    fi

    echo "Still running fio"
    sleep 60
  done
}

run_fio_fileopenclose_multiple_pods_run() {
  local pod_name=$1
  local mount_point=$2
  local result_dir=$3
  local file_name_prefix=$4
  local num_files=$5
  local num_jobs_parallel=$6
  local runtime=$7
  local storage_name=$8

  local target_directory="${mount_point}/${pod_name}"
  local num_files_per_job=$((num_files / num_jobs_parallel))

  echo "Run fio"

  set +x # disable debug output because it will mess up the output of fio

  local command="fio --name=$file_name_prefix --filesize=4096 --directory=$target_directory --thread=1 --readwrite=rw --nrfiles=$num_files_per_job --ioengine=fileopenclose --numjobs=$num_jobs_parallel --time_based --runtime=$runtime --openfiles=1 --group_report --output-format=json"

  # execute the actual run for metrics collection
  echo "Run command: $command"
  start_time=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
  run_kubectl_exec $pod_name fio "$command" > >(tee $result_dir/result-${pod_name}.log) 2> >(tee $result_dir/error-${pod_name}.log >&2) &
  end_time=$(date -u -d "$start_time + $runtime seconds" +"%Y-%m-%dT%H:%M:%SZ")

  metadata_json="{\"NumFiles\": \"$num_files\", \"IoDepth\": \"$num_jobs_parallel\", \"StorageName\": \"$storage_name\", \"StartTime\": \"$start_time\", \"EndTime\": \"$end_time\"}"
  echo "$metadata_json" > $result_dir/metadata-${pod_name}.log

  if $DEBUG; then # re-enable debug output if DEBUG is set
    set -x
  fi
}

collect_result_disk_fio() {
  local result_dir=$1
  local run_link=$2

  echo "collecting fio results from $result_dir/fio.log"

  # TODO(@guwe): add pricing
  DATA_DISK_PRICE_PER_MONTH="${DATA_DISK_PRICE_PER_MONTH:=0}"

  metadata="$(cat $result_dir/metadata.log)"
  result="$result_dir/fio.log"
  echo "========= collecting ${result} ==========="
  cat $result

  read_iops_avg=$(cat $result | jq '.jobs[0].read.iops_mean')
  read_bw_avg=$(cat $result | jq '.jobs[0].read.bw_mean')
  read_lat_avg=$(cat $result | jq '.jobs[0].read.clat_ns.mean')
  write_iops_avg=$(cat $result | jq '.jobs[0].write.iops_mean')
  write_bw_avg=$(cat $result | jq '.jobs[0].write.bw_mean')
  write_lat_avg=$(cat $result | jq '.jobs[0].write.clat_ns.mean')
  read_lat_p50=$(cat $result | jq '.jobs[0].read.clat_ns.percentile."50.000000"')
  read_lat_p99=$(cat $result | jq '.jobs[0].read.clat_ns.percentile."99.000000"')
  read_lat_p999=$(cat $result | jq '.jobs[0].read.clat_ns.percentile."99.900000"')
  write_lat_p50=$(cat $result | jq '.jobs[0].write.clat_ns.percentile."50.000000"')
  write_lat_p99=$(cat $result | jq '.jobs[0].write.clat_ns.percentile."99.000000"')
  write_lat_p999=$(cat $result | jq '.jobs[0].write.clat_ns.percentile."99.900000"')

  data=$(jq --null-input \
    --arg timestamp "$(date -u +"%Y-%m-%dT%H:%M:%SZ")" \
    --arg method "${method}" \
    --arg location "$REGION" \
    --arg vm_size "$MACHINE_TYPE" \
    --arg run_url "$run_link" \
    --arg cloud "$CLOUD" \
    --arg target_iops "$TARGET_IOPS" \
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
    --arg read_lat_avg "$read_lat_avg" \
    --arg write_iops_avg "$write_iops_avg" \
    --arg write_bw_avg "$write_bw_avg" \
    --arg write_lat_avg "$write_lat_avg" \
    --arg read_lat_p50 "$read_lat_p50" \
    --arg read_lat_p99 "$read_lat_p99" \
    --arg read_lat_p999 "$read_lat_p999" \
    --arg write_lat_p50 "$write_lat_p50" \
    --arg write_lat_p99 "$write_lat_p99" \
    --arg write_lat_p999 "$write_lat_p999" \
    --arg metadata "$metadata" \
    '{
      timestamp: $timestamp,
      method: $method,
      location: $location,
      vm_size: $vm_size,
      run_url: $run_url,
      cloud: $cloud,
      target_iops: $target_iops,
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
      read_lat_avg: $read_lat_avg,
      write_iops_avg: $write_iops_avg,
      write_bw_avg: $write_bw_avg,
      write_lat_avg: $write_lat_avg,
      read_lat_p50: $read_lat_p50,
      read_lat_p99: $read_lat_p99,
      read_lat_p999: $read_lat_p999,
      write_lat_p50: $write_lat_p50,
      write_lat_p99: $write_lat_p99,
      write_lat_p999: $write_lat_p999,
      metadata: $metadata
    }')

  echo $data >> $result_dir/results.json
}

collect_result_blob_fio() {
  local result_dir=$1
  local run_link=$2

  echo "collecting fio results from $result_dir/fio.log"


  metadata="$(cat $result_dir/metadata.log)"
  result="$result_dir/fio.log"
  echo "========= collecting ${result} ==========="
  cat $result

  read_iops_avg=$(cat $result | jq '.jobs[0].read.iops_mean')
  read_bw_avg=$(cat $result | jq '.jobs[0].read.bw_mean')
  read_lat_avg=$(cat $result | jq '.jobs[0].read.clat_ns.mean')
  write_iops_avg=$(cat $result | jq '.jobs[0].write.iops_mean')
  write_bw_avg=$(cat $result | jq '.jobs[0].write.bw_mean')
  write_lat_avg=$(cat $result | jq '.jobs[0].write.clat_ns.mean')
  read_lat_p50=$(cat $result | jq '.jobs[0].read.clat_ns.percentile."50.000000"')
  read_lat_p99=$(cat $result | jq '.jobs[0].read.clat_ns.percentile."99.000000"')
  read_lat_p999=$(cat $result | jq '.jobs[0].read.clat_ns.percentile."99.900000"')
  write_lat_p50=$(cat $result | jq '.jobs[0].write.clat_ns.percentile."50.000000"')
  write_lat_p99=$(cat $result | jq '.jobs[0].write.clat_ns.percentile."99.000000"')
  write_lat_p999=$(cat $result | jq '.jobs[0].write.clat_ns.percentile."99.900000"')

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
    --arg read_lat_avg "$read_lat_avg" \
    --arg write_iops_avg "$write_iops_avg" \
    --arg write_bw_avg "$write_bw_avg" \
    --arg write_lat_avg "$write_lat_avg" \
    --arg read_lat_p50 "$read_lat_p50" \
    --arg read_lat_p99 "$read_lat_p99" \
    --arg read_lat_p999 "$read_lat_p999" \
    --arg write_lat_p50 "$write_lat_p50" \
    --arg write_lat_p99 "$write_lat_p99" \
    --arg write_lat_p999 "$write_lat_p999" \
    --arg metadata "$metadata" \
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
      read_lat_avg: $read_lat_avg,
      write_iops_avg: $write_iops_avg,
      write_bw_avg: $write_bw_avg,
      write_lat_avg: $write_lat_avg,
      read_lat_p50: $read_lat_p50,
      read_lat_p99: $read_lat_p99,
      read_lat_p999: $read_lat_p999,
      write_lat_p50: $write_lat_p50,
      write_lat_p99: $write_lat_p99,
      write_lat_p999: $write_lat_p999,
      metadata: $metadata
    }')

  echo $data >> $result_dir/results.json
}

collect_result_fileshare_fio() {
  local result_dir=$1
  local run_link=$2

  echo "collecting small file results from $result_dir/worldpress.log"
  local worldpress_log="$result_dir/worldpress.log"
  cat $worldpress_log
  small_file_rw=$(cat $worldpress_log | grep real | awk '{print $2}')
  if [ -z "$small_file_rw" ]; then
    echo "small_file_rw is empty, set to 0"
    small_file_rw="0"
  fi

  echo "collecting fio results from $result_dir/fio.log"

  metadata="$(cat $result_dir/metadata.log)"
  result="$result_dir/fio.log"
  echo "========= collecting ${result} ==========="
  cat $result

  read_iops_avg=$(cat $result | jq '.jobs[0].read.iops_mean')
  read_bw_avg=$(cat $result | jq '.jobs[0].read.bw_mean')
  read_lat_avg=$(cat $result | jq '.jobs[0].read.clat_ns.mean')
  write_iops_avg=$(cat $result | jq '.jobs[0].write.iops_mean')
  write_bw_avg=$(cat $result | jq '.jobs[0].write.bw_mean')
  write_lat_avg=$(cat $result | jq '.jobs[0].write.clat_ns.mean')
  read_lat_p50=$(cat $result | jq '.jobs[0].read.clat_ns.percentile."50.000000"')
  read_lat_p99=$(cat $result | jq '.jobs[0].read.clat_ns.percentile."99.000000"')
  read_lat_p999=$(cat $result | jq '.jobs[0].read.clat_ns.percentile."99.900000"')
  write_lat_p50=$(cat $result | jq '.jobs[0].write.clat_ns.percentile."50.000000"')
  write_lat_p99=$(cat $result | jq '.jobs[0].write.clat_ns.percentile."99.000000"')
  write_lat_p999=$(cat $result | jq '.jobs[0].write.clat_ns.percentile."99.900000"')

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
    --arg read_lat_avg "$read_lat_avg" \
    --arg write_iops_avg "$write_iops_avg" \
    --arg write_bw_avg "$write_bw_avg" \
    --arg write_lat_avg "$write_lat_avg" \
    --arg small_file_rw "$small_file_rw" \
    --arg read_lat_p50 "$read_lat_p50" \
    --arg read_lat_p99 "$read_lat_p99" \
    --arg read_lat_p999 "$read_lat_p999" \
    --arg write_lat_p50 "$write_lat_p50" \
    --arg write_lat_p99 "$write_lat_p99" \
    --arg write_lat_p999 "$write_lat_p999" \
    --arg metadata "$metadata" \
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
      read_lat_avg: $read_lat_avg,
      write_iops_avg: $write_iops_avg,
      write_bw_avg: $write_bw_avg,
      write_lat_avg: $write_lat_avg,
      small_file_rw: $small_file_rw,
      read_lat_p50: $read_lat_p50,
      read_lat_p99: $read_lat_p99,
      read_lat_p999: $read_lat_p999,
      write_lat_p50: $write_lat_p50,
      write_lat_p99: $write_lat_p99,
      write_lat_p999: $write_lat_p999,
      metadata: $metadata
    }')

  echo $data >> $result_dir/results.json
}

collect_result_fileshare_fio_mulitple_pods() {
  local result_dir=$1
  local run_link=$2

  echo "collecting fio results from $result_dir/result-*.log"

  cd $result_dir
  results=$(ls -N result*)
  echo $results
  errors=$(ls -N error*)
  for error in $errors
  {
    cat $error
  }
  logs=$(ls -N log*)
  for log in $logs
  {
    cat $log
  }
  events=$(ls -N event*)
  for event in $events
  {
    cat $event
  }

  for result in $results
  {
    pod_name=$(echo "$result" | sed 's/result-\(.*\)\.log/\1/')

    metadata="$(cat metadata-${pod_name}.log)"
    echo "========= collecting ${result} ==========="
    cat $result

    read_count=$(cat $result | jq '.jobs[0].read.clat_ns.N')
    read_runtime_ms=$(cat $result | jq '.jobs[0].read.runtime')
    read_iops_avg=$(echo "scale=2; $read_count * 1000 / $read_runtime_ms" | bc)
    write_count=$(cat $result | jq '.jobs[0].write.clat_ns.N')
    write_runtime_ms=$(cat $result | jq '.jobs[0].write.runtime')
    write_iops_avg=$(echo "scale=2; $write_count * 1000 / $write_runtime_ms" | bc)
    read_bw_avg=$(cat $result | jq '.jobs[0].read.bw_mean')
    read_lat_avg=$(cat $result | jq '.jobs[0].read.clat_ns.mean')
    write_bw_avg=$(cat $result | jq '.jobs[0].write.bw_mean')
    write_lat_avg=$(cat $result | jq '.jobs[0].write.clat_ns.mean')
    read_lat_p50=$(cat $result | jq '.jobs[0].read.clat_ns.percentile."50.000000"')
    read_lat_p99=$(cat $result | jq '.jobs[0].read.clat_ns.percentile."99.000000"')
    read_lat_p999=$(cat $result | jq '.jobs[0].read.clat_ns.percentile."99.900000"')
    write_lat_p50=$(cat $result | jq '.jobs[0].write.clat_ns.percentile."50.000000"')
    write_lat_p99=$(cat $result | jq '.jobs[0].write.clat_ns.percentile."99.000000"')
    write_lat_p999=$(cat $result | jq '.jobs[0].write.clat_ns.percentile."99.900000"')

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
      --arg read_lat_avg "$read_lat_avg" \
      --arg write_iops_avg "$write_iops_avg" \
      --arg write_bw_avg "$write_bw_avg" \
      --arg write_lat_avg "$write_lat_avg" \
      --arg small_file_rw "$small_file_rw" \
      --arg read_lat_p50 "$read_lat_p50" \
      --arg read_lat_p99 "$read_lat_p99" \
      --arg read_lat_p999 "$read_lat_p999" \
      --arg write_lat_p50 "$write_lat_p50" \
      --arg write_lat_p99 "$write_lat_p99" \
      --arg write_lat_p999 "$write_lat_p999" \
      --arg metadata "$metadata" \
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
        read_lat_avg: $read_lat_avg,
        write_iops_avg: $write_iops_avg,
        write_bw_avg: $write_bw_avg,
        write_lat_avg: $write_lat_avg,
        small_file_rw: $small_file_rw,
        read_lat_p50: $read_lat_p50,
        read_lat_p99: $read_lat_p99,
        read_lat_p999: $read_lat_p999,
        write_lat_p50: $write_lat_p50,
        write_lat_p99: $write_lat_p99,
        write_lat_p999: $write_lat_p999,
        metadata: $metadata
      }')

    echo $data >> $result_dir/results.json
  }
}