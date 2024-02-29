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

  mkdir -p $result_dir

  local command="sudo df -hT $mount_point"
  run_ssh $privatekey_path ubuntu $egress_ip_address 2222 "$command"

  local file_size=$((10*1024*1024*1024))

  local file_path="${mount_point}/benchtest"

  local methods=("randread" "read" "randwrite" "write")
  local iodepths=(1 4 8 16)
  local blocksizes=("4k" "256k")

  echo "Run fio"

  set +x # disable debug output because it will mess up the output of fio
  for method in "${methods[@]}"
  do
    for iodepth in "${iodepths[@]}"
    do
      for bs in "${blocksizes[@]}"
      do
        metadata_json="{\"BlockSize\": \"$bs\", \"IoDepth\": \"$iodepth\", \"Operation\": \"$method\", \"FileSize\": \"$file_size\"}"
        echo "$metadata_json" > $result_dir/metadata-${method}-${iodepth}-${bs}.log
        local command="sudo fio --name=benchtest --size=$file_size --filename=$file_path --direct=1 --rw=$method --ioengine=libaio --bs=$bs --iodepth=$iodepth --time_based --runtime=60 --output-format=json"

        # prepare files for the actual run using fio option --create_only=1
        setup_command="${command} --create_only=1"
        echo "Run command: $setup_command"
        run_ssh $privatekey_path ubuntu $egress_ip_address 2222 "$setup_command"
        sleep 30 # wait to clean any potential throttle / cache

        # execute the actual run for metrics collection
        echo "Run command: $command"
        run_ssh $privatekey_path ubuntu $egress_ip_address 2222 "$command" | tee $result_dir/fio-${method}-${iodepth}-${bs}.log
        sleep 30 # wait to clean any potential throttle / cache
      done
    done
  done

  if $DEBUG; then # re-enable debug output if DEBUG is set
    set -x
  fi
}


collect_result_disk_fio() {
  local result_dir=$1
  local run_link=$2

  echo "collecting fio results from $result_dir/fio-*.log"

  local methods=("randread" "read" "randwrite" "write")
  local iodepths=(1 4 8 16)
  local blocksizes=("4k" "256k")

  # TODO(@guwe): add pricing
  DATA_DISK_PRICE_PER_MONTH="${DATA_DISK_PRICE_PER_MONTH:=0}"

  for method in "${methods[@]}"
  do
    for iodepth in "${iodepths[@]}"
    do
      for bs in "${blocksizes[@]}"
      do
        metadata="$(cat $result_dir/metadata-${method}-${iodepth}-${bs}.log)"
        result="$result_dir/fio-${method}-${iodepth}-${bs}.log"
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
      done
    done
  done
}

collect_result_blob_fio() {
  local result_dir=$1
  local run_link=$2

  echo "collecting fio results from $result_dir/fio-*.log"

  local methods=("randread" "read" "randwrite" "write")
  local iodepths=(1 4 8 16)
  local blocksizes=("4k" "256k")

  for method in "${methods[@]}"
  do
    for iodepth in "${iodepths[@]}"
    do
      for bs in "${blocksizes[@]}"
      do
        metadata="$(cat $result_dir/metadata-${method}-${iodepth}-${bs}.log)"
        result="$result_dir/fio-${method}-${iodepth}-${bs}.log"
        echo "========= collecting ${result} ==========="
        cat $result

        read_iops_avg=$(cat $result | jq '.jobs[0].read.iops_mean')
        read_bw_avg=$(cat $result | jq '.jobs[0].read.bw_mean')
        read_lat_avg=$(cat $result | jq '.jobs[0].read.clat_ns.mean')
        write_iops_avg=$(cat $result | jq '.jobs[0].write.iops_mean')
        write_bw_avg=$(cat $result | jq '.jobs[0].write.bw_mean')
        write_lat_avg=$(cat $result | jq '.jobs[0].write.clat_ns.mean')

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
      done
    done
  done
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

  echo "collecting fio results from $result_dir/fio-*.log"

  local methods=("randread" "read" "randwrite" "write")
  local iodepths=(1 4 8 16)
  local blocksizes=("4k" "256k")

  for method in "${methods[@]}"
  do
    for iodepth in "${iodepths[@]}"
    do
      for bs in "${blocksizes[@]}"
      do
        metadata="$(cat $result_dir/metadata-${method}-${iodepth}-${bs}.log)"
        result="$result_dir/fio-${method}-${iodepth}-${bs}.log"
        echo "========= collecting ${result} ==========="
        cat $result

        read_iops_avg=$(cat $result | jq '.jobs[0].read.iops_mean')
        read_bw_avg=$(cat $result | jq '.jobs[0].read.bw_mean')
        read_lat_avg=$(cat $result | jq '.jobs[0].read.clat_ns.mean')
        write_iops_avg=$(cat $result | jq '.jobs[0].write.iops_mean')
        write_bw_avg=$(cat $result | jq '.jobs[0].write.bw_mean')
        write_lat_avg=$(cat $result | jq '.jobs[0].write.clat_ns.mean')

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
      done
    done
  done
}