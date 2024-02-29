#!/bin/bash

sudo perl -pi -e 's/^#?Port 22$/Port 2222/' /etc/ssh/sshd_config
sudo service ssh restart

sudo apt-get update && sudo apt-get install iperf -y

for i in {0..1}
do
  nohup iperf --server --port "2000$i" &> /dev/null &
done

nohup iperf --server --udp --port 20002 &> /dev/null &