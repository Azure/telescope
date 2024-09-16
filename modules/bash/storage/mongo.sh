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
    local command="/app/scripts/run_ycsb.sh -t mongo-server-0.mongo-server -w $workload_name -o $result_dir"
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
  read_ops_avg=$(cat $result | grep "\[READ\],\ Operations" |  cut -d ',' -f 3 | cut -d ' ' -f 2)
  read_lat_avg=$(cat $result | grep "\[READ\],\ AverageLatency" |  cut -d ',' -f 3 | cut -d ' ' -f 2)
  read_lat_min=$(cat $result | grep "\[READ\],\ MinLatency" |  cut -d ',' -f 3 | cut -d ' ' -f 2)
  read_lat_max=$(cat $result | grep "\[READ\],\ MaxLatency" |  cut -d ',' -f 3 | cut -d ' ' -f 2)
  read_lat_p95=$(cat $result | grep "\[READ\],\ 95thPercentileLatency" |  cut -d ',' -f 3 | cut -d ' ' -f 2)
  read_lat_p99=$(cat $result | grep "\[READ\],\ 99thPercentileLatency" |  cut -d ',' -f 3 | cut -d ' ' -f 2)

  data=$(jq --null-input \
    --arg run_time_ms "$run_time_ms" \
    --arg iops_avg "$iops_avg" \
    --arg insert_ops_avg "$insert_ops_avg" \
    --arg insert_lat_avg "$insert_lat_avg" \
    --arg insert_lat_min "$insert_lat_min" \
    --arg insert_lat_max "$insert_lat_max" \
    --arg insert_lat_p95 "$insert_lat_p95" \
    --arg insert_lat_p99 "$insert_lat_p99" \
    --arg read_ops_avg "$read_ops_avg" \
    --arg read_lat_avg "$read_lat_avg" \
    --arg read_lat_min "$read_lat_min" \
    --arg read_lat_max "$read_lat_max" \
    --arg read_lat_p95 "$read_lat_p95" \
    --arg read_lat_p99 "$read_lat_p99" \
    '{
      run_time_ms: $run_time_ms,
      iops_avg: $iops_avg,
      insert_ops_avg: $insert_ops_avg,
      insert_lat_avg: $insert_lat_avg,
      insert_lat_min: $insert_lat_min,
      insert_lat_max: $insert_lat_max,
      insert_lat_p95: $insert_lat_p95,
      insert_lat_p99: $insert_lat_p99,
      read_ops_avg: $read_ops_avg,
      read_lat_avg: $read_lat_avg,
      read_lat_min: $read_lat_min,
      read_lat_max: $read_lat_max,
      read_lat_p95: $read_lat_p95,
      read_lat_p99: $read_lat_p99
    }')

   echo $data >> $result_dir/results.json
}