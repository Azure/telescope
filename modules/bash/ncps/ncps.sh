source ./modules/bash/utils.sh

set_up_ncps() {
  local public_ip=$1
  local privatekey_path=$2
  local is_server=$3

  run_scp_remote $privatekey_path ubuntu $public_ip 2222 ./modules/bash/ncps/src /home/ubuntu/ncps
  run_ssh $privatekey_path ubuntu $public_ip 2222 "cd /home/ubuntu/ncps/src && sudo gcc sockwiz.c ncps.c -lpthread -O3 -o /bin/ncps"

  if [ "$is_server" == "true" ]; then
    run_ssh $privatekey_path ubuntu $public_ip 2222 "nohup ncps -s &> /dev/null &"
  fi
}