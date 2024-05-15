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
#   - $6: The unique name of the result file
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
  run_ssh $privatekey_path ubuntu $client_ip 2222 "$wrkCommand" > ${result_dir}/${result_file_name}.txt
}

collect_wrk() {
  
}