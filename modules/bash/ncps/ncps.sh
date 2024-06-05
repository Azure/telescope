source ./modules/bash/utils.sh

# Description:
#   This function is used to set up ncps in the virtual machine
#
# Parameters:
#   - $1: The public IP address of the virtual machine
#   - $2: The private key path to use
#   - $3: The role of the virtual machine (e.g. "server" or "client")
set_up_ncps() {
  local public_ip=$1
  local privatekey_path=$2
  local role=$3

  run_scp_remote $privatekey_path ubuntu $public_ip 2222 ./modules/bash/ncps/src /home/ubuntu/ncps
  run_ssh $privatekey_path ubuntu $public_ip 2222 "cd /home/ubuntu/ncps/src && sudo gcc sockwiz.c ncps.c -lpthread -O3 -o /bin/ncps"

  if [ "$role" == "server" ]; then
    run_ssh $privatekey_path ubuntu $public_ip 2222 "nohup ncps -s &> /dev/null &"
  fi
}

# Description:
#   This function is used to run wrk command
#
# Parameters:
#   - $1: The destination IP address
#   - $2: The client IP address to SSH into
#   - $3: The ncps options to use (e.g. "-wt 10 -t 60 -r 2")
#   - $4: The private key path to use
#   - $5: The result directory to store the result file
#   - $6: The unique name of the raw wrk result file
#
# Usage: run_wrk <destination_ip> <client_ip> <wrk_options> <privatekey_path> <result_dir> <result_file_name>
run_ncps() {
  local destination_ip=$1
  local client_ip=$2
  local ncps_options=$3
  local privatekey_path=$4
  local result_dir=$5
  local result_file_name=$6

  ncpsCommand="ncps -c $destination_ip -sil $ncps_options"
  echo "Run test command: $ncpsCommand"
  run_ssh $privatekey_path ubuntu $client_ip 2222 "$ncpsCommand" > ${result_dir}/${result_file_name}.log
}