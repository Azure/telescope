source ./modules/bash/utils.sh

set -e

if $DEBUG; then
    set -x
fi
start_mongo_replica_set() {
    local pod_name=$1

    echo "Start replica set in server"

    set +x # disable debug output because it will mess up the output of fio

    local command="/app/scripts/start_replset.sh"
    
    # start the replica set
    echo "Run command: $command"
    run_kubectl_exec "$pod_name" mongo-server "$command" > rs_start_output.txt
    cat rs_start_output.txt

    if $DEBUG; then # re-enable debug output if DEBUG is set
        set -x
    fi
}
run_ycsb_on_pod() {
    local pod_name=$1
    local workload_name=$2
    local result_dir=$3
    
    mkdir -p $result_dir

    echo "Run YCSB"

    set +x # disable debug output because it will mess up the output of fio

    #local command="fio --name=benchtest --size=$file_size --filename=$file_path --direct=1 --rw=$method --ioengine=libaio --bs=$bs --iodepth=$iodepth --time_based --runtime=$runtime --output-format=json"
    local command="/app/scripts/run_ycsb.sh /app mongo-server-0.mongo-server $workload_name $result_dir"
    # prepare files for the actual run using fio option --create_only=1
    #setup_command="${command} --create_only=1"
    #echo "Run command: $setup_command"
    #run_kubectl_exec $pod_name fio "$setup_command"
    #sleep 30 # wait to clean any potential throttle / cache

    # execute the actual run for metrics collection
    echo "Run command: $command"
    start_time=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
    run_kubectl_exec $pod_name mongo-client "$command" | tee $result_dir/ycsb.log
    end_time=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

    #metadata_json="{\"BlockSize\": \"$bs\", \"IoDepth\": \"$iodepth\", \"Operation\": \"$method\", \"FileSize\": \"$file_size\", \"StorageName\": \"$storage_name\", \"StartTime\": \"$start_time\", \"EndTime\": \"$end_time\"}"
    echo "$metadata_json" > $result_dir/metadata.log

    if $DEBUG; then # re-enable debug output if DEBUG is set
        set -x
    fi
}

collect_result_disk_ycsb() {
  local result_dir=$1
  local run_link=$2

  cat $result_dir/ycsb.log
  #cat $result_dir/ycsb.log >> $result_dir/results.txt

  echo "collecting ycsb results from $result_dir/ycsb.log"

#   # TODO(@guwe): add pricing
#   DATA_DISK_PRICE_PER_MONTH="${DATA_DISK_PRICE_PER_MONTH:=0}"

  metadata="$(cat $result_dir/metadata.log)"
  result="$result_dir/ycsb.log"
  echo "========= collecting ${result} ==========="
  cat $result

  run_time_ms=$(cat $result | grep "\[OVERALL\],\ RunTime" |  cut -d ',' -f 3 | cut -d ' ' -f 2)
  iops_avg=$(cat $result | grep "\[OVERALL\],\ Throughput" |  cut -d ',' -f 3 | cut -d ' ' -f 2)
  insert_ops_avg=$(cat $result | grep "\[INSERT\],\ Operations" |  cut -d ',' -f 3 | cut -d ' ' -f 2)
  insert_lat_avg=$(cat $result | grep "\[INSERT\],\ AverageLatency" |  cut -d ',' -f 3 | cut -d ' ' -f 2)
  insert_lat_min=$(cat $result | grep "\[INSERT\],\ MinLatency" |  cut -d ',' -f 3 | cut -d ' ' -f 2)
  insert_lat_max=$(cat $result | grep "\[INSERT\],\ MaxLatency" |  cut -d ',' -f 3 | cut -d ' ' -f 2)
  insert_lat_p95=$(cat $result | grep "\[INSERT\],\ 95thPercentileLatency" |  cut -d ',' -f 3 | cut -d ' ' -f 2)
  insert_lat_p99=$(cat $result | grep "\[INSERT\],\ 99thPercentileLatency" |  cut -d ',' -f 3 | cut -d ' ' -f 2)
#   read_iops_avg=$(cat $result | jq '.jobs[0].read.iops_mean')
#   read_bw_avg=$(cat $result | jq '.jobs[0].read.bw_mean')
#   read_lat_avg=$(cat $result | jq '.jobs[0].read.clat_ns.mean')
#   write_iops_avg=$(cat $result | jq '.jobs[0].write.iops_mean')
#   write_bw_avg=$(cat $result | jq '.jobs[0].write.bw_mean')
#   write_lat_avg=$(cat $result | jq '.jobs[0].write.clat_ns.mean')
#   read_lat_p50=$(cat $result | jq '.jobs[0].read.clat_ns.percentile."50.000000"')
#   read_lat_p99=$(cat $result | jq '.jobs[0].read.clat_ns.percentile."99.000000"')
#   read_lat_p999=$(cat $result | jq '.jobs[0].read.clat_ns.percentile."99.900000"')
#   write_lat_p50=$(cat $result | jq '.jobs[0].write.clat_ns.percentile."50.000000"')
#   write_lat_p99=$(cat $result | jq '.jobs[0].write.clat_ns.percentile."99.000000"')
#   write_lat_p999=$(cat $result | jq '.jobs[0].write.clat_ns.percentile."99.900000"')

   data=$(jq --null-input \
    --arg run_time_ms "$run_time_ms" \
    --arg iops_avg "$iops_avg" \
    --arg insert_ops_avg "$insert_ops_avg" \
    --arg insert_lat_avg "$insert_lat_avg" \
    --arg insert_lat_min "$insert_lat_min" \
    --arg insert_lat_max "$insert_lat_max" \
    --arg insert_lat_p95 "$insert_lat_p95" \
    --arg insert_lat_p99 "$insert_lat_p99" \
    '{
      run_time_ms: $run_time_ms,
      iops_avg: $iops_avg,
      insert_ops_avg: $insert_ops_avg,
      insert_lat_avg: $insert_lat_avg,
      insert_lat_min: $insert_lat_min,
      insert_lat_max: $insert_lat_max,
      insert_lat_p95: $insert_lat_p95,
      insert_lat_p99: $insert_lat_p99
    }')

#     --arg timestamp "$(date -u +"%Y-%m-%dT%H:%M:%SZ")" \
#     --arg method "${method}" \
#     --arg location "$REGION" \
#     --arg vm_size "$MACHINE_TYPE" \
#     --arg run_url "$run_link" \
#     --arg cloud "$CLOUD" \
#     --arg target_iops "$TARGET_IOPS" \
#     --arg case_name "$CASE_NAME" \
#     --arg data_disk_type "$DATA_DISK_TYPE" \
#     --arg data_disk_size "$DATA_DISK_SIZE_GB" \
#     --arg data_disk_tier "$DATA_DISK_TIER" \
#     --arg data_disk_iops_rw "$DATA_DISK_IOPS_READ_WRITE" \
#     --arg data_disk_iops_r "$DATA_DISK_IOPS_READ_ONLY" \
#     --arg data_disk_mbps_rw "$DATA_DISK_MBPS_READ_WRITE" \
#     --arg data_disk_mbps_r "$DATA_DISK_MBPS_READ_ONLY" \
#     --arg data_disk_price_per_month "$DATA_DISK_PRICE_PER_MONTH" \
#     --arg read_iops_avg "$read_iops_avg" \
#     --arg read_bw_avg "$read_bw_avg" \
#     --arg read_lat_avg "$read_lat_avg" \
#     --arg write_iops_avg "$write_iops_avg" \
#     --arg write_bw_avg "$write_bw_avg" \
#     --arg write_lat_avg "$write_lat_avg" \
#     --arg read_lat_p50 "$read_lat_p50" \
#     --arg read_lat_p99 "$read_lat_p99" \
#     --arg read_lat_p999 "$read_lat_p999" \
#     --arg write_lat_p50 "$write_lat_p50" \
#     --arg write_lat_p99 "$write_lat_p99" \
#     --arg write_lat_p999 "$write_lat_p999" \
#     --arg metadata "$metadata" \
#     '{
#       timestamp: $timestamp,
#       method: $method,
#       location: $location,
#       vm_size: $vm_size,
#       run_url: $run_url,
#       cloud: $cloud,
#       target_iops: $target_iops,
#       case_name: $case_name,
#       data_disk_type: $data_disk_type,
#       data_disk_size: $data_disk_size,
#       data_disk_tier: $data_disk_tier,
#       data_disk_iops_rw: $data_disk_iops_rw,
#       data_disk_iops_r: $data_disk_iops_r,
#       data_disk_mbps_rw: $data_disk_mbps_rw,
#       data_disk_mbps_r: $data_disk_mbps_r,
#       data_disk_price_per_month: $data_disk_price_per_month,
#       read_iops_avg: $read_iops_avg,
#       read_bw_avg: $read_bw_avg,
#       read_lat_avg: $read_lat_avg,
#       write_iops_avg: $write_iops_avg,
#       write_bw_avg: $write_bw_avg,
#       write_lat_avg: $write_lat_avg,
#       read_lat_p50: $read_lat_p50,
#       read_lat_p99: $read_lat_p99,
#       read_lat_p999: $read_lat_p999,
#       write_lat_p50: $write_lat_p50,
#       write_lat_p99: $write_lat_p99,
#       write_lat_p999: $write_lat_p999,
#       metadata: $metadata
#     }')

   echo $data >> $result_dir/results.json
}