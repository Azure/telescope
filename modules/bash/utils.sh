#!/bin/bash

run_ssh() {
  local privatekey_path=$1
  local user=$2
  local ip=$3
  local port=$4
  local command=$5

  sshCommand="ssh -i $privatekey_path -A -p $port $user@$ip -2 -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no -o IdentitiesOnly=yes -o PreferredAuthentications=publickey -o PasswordAuthentication=no -o ConnectTimeout=5 -o GSSAPIAuthentication=no -o ServerAliveInterval=30 -o ServerAliveCountMax=10 $command"
  $sshCommand
}

run_scp_remote() {
  local privatekey_path=$1
  local user=$2
  local ip=$3
  local port=$4
  local source=$5
  local destination=$6

  scpCommand="scp -i $privatekey_path -P $port -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no -o IdentitiesOnly=yes -o PreferredAuthentications=publickey -o PasswordAuthentication=no -o ConnectTimeout=5 -o GSSAPIAuthentication=no -o ServerAliveInterval=30 -o ServerAliveCountMax=10 $source $user@$ip:$destination"
  $scpCommand
}

run_scp_local() {
  local privatekey_path=$1
  local user=$2
  local ip=$3
  local port=$4
  local source=$5
  local destination=$6

  scpCommand="scp -i $privatekey_path -P $port -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no -o IdentitiesOnly=yes -o PreferredAuthentications=publickey -o PasswordAuthentication=no -o ConnectTimeout=5 -o GSSAPIAuthentication=no -o ServerAliveInterval=30 -o ServerAliveCountMax=10 $user@$ip:$source $destination"
  $scpCommand
}

check_ssh_connection() {
  local ip_address=$1
  local privatekey_path=$2

  echo "Check ssh connection"
  max_retries=10
  i=0
  status=1
  while true
  do
    echo "run_ssh $privatekey_path ubuntu $ip_address hostname"
    run_ssh $privatekey_path ubuntu $ip_address hostname
    status=$?
    i=$((i+1))

    if [ "$status" -eq 0 ]; then
      break
    elif [ "$i" -eq "$max_retries" ]; then
      echo "Client not reachable after $max_retries retries"
      exit 1
    fi

    sleep 30
  done
}

create_file() {
  local dir_name=$1
  local file_name=$2

  echo "Creating folder $dir_name and file $file_name"
  mkdir -p $dir_name
  touch $file_name
}

fetch_proc_net() {
  local ip_address=$1
  local privatekey_path=$2
  local port_num=$3
  local protocol=$4

  max_rx_queue=0
  max_drops=0
  source="/proc/net/${protocol}"
  destination="/tmp/proc-net-${protocol}"
  for i in {1..60}; do
    run_ssh $privatekey_path ubuntu $ip_address "cat $source" > $destination
    total_drops=0
    while read line; do
      port_hex=$(printf "%X" $port_num)
      if echo "$line" | grep -q $port_hex; then
          rx_queue_hex=$(echo $line | awk '{print $5}' | awk -F: '{print $2}')
          rx_queue=$(printf "%d" "0x$rx_queue_hex")

          if [ "$protocol" == "udp" ]; then
            drops=$(echo $line | awk '{print $NF}')
          elif [ "$protocol" == "tcp" ]; then
            drops_hex=$(echo $line | awk '{print $7}')
            drops=$(printf "%d" "0x$drops_hex")
          fi

          if (( rx_queue > max_rx_queue )); then
            max_rx_queue=$rx_queue
          fi
          total_drops=$((total_drops + drops))
       fi
    done < $destination
    if (( total_drops > max_drops )); then
        max_drops=$total_drops
    fi
    sleep 1
  done

  echo "$max_rx_queue $max_drops"
}