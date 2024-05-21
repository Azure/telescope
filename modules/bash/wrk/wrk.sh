source ./modules/bash/utils.sh

# Description:
#   This function is used to run wrk command
#
# Parameters:
#   - $1: The destination IP address
#   - $2: The client IP address to SSH into
#   - $3: The wrk options to use (e.g. "-t2 -c10 -d30s")
#   - $4: The private key path to use
#   - $5: The result directory to store the result file
#   - $6: The unique name of the raw wrk result file
#
# Usage: run_wrk <destination_ip> <client_ip> <wrk_options> <privatekey_path> <result_dir> <result_file_name>
run_wrk() {
  local destination_ip=$1
  local client_ip=$2
  local wrk_options=$3
  local privatekey_path=$4
  local result_dir=$5
  local result_file_name=$6

  wrkCommand="wrk $wrk_options --latency http://$destination_ip"
  echo "Run test command: $wrkCommand"
  run_ssh $privatekey_path ubuntu $client_ip 2222 "$wrkCommand" > ${result_dir}/${result_file_name}.log
}

# Description:
#   This function is used to collect the result of wrk
#
# Parameters:
#   - $1: The result directory
#   - $2: The unique name of the raw wrk result file
#   - $3: The pipeline run URL
#   - $4: The cloud information
#
# Usage: collect_wrk <result_dir> <result_file_name> <run_url> <cloud_info>
collect_wrk() {
  local result_dir=$1
  local result_file_name=$2
  local run_url=$3
  local cloud_info=$4

  result=$(python3 ./modules/python/wrk/parser.py ${result_dir}/${result_file_name}.log)
  echo "wrk result: $result"

  data=$(jq --null-input \
    --arg timestamp "$(date -u +"%Y-%m-%dT%H:%M:%SZ")" \
    --arg cloud_info "$cloud_info" \
    --arg result "$result" \
    --arg run_url "$run_url" \
    '{timestamp: $timestamp, cloud_info: $cloud_info, result: $result, run_url: $run_url}')
  
  touch $result_dir/results.json
  echo $data >> $result_dir/results.json
}