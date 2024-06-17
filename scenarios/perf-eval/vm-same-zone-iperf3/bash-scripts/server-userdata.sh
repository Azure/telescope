#!/bin/bash

sudo perl -pi -e 's/^#?Port 22$/Port 2222/' /etc/ssh/sshd_config
sudo service ssh restart

sudo apt-get update && sudo apt-get install iperf3 -y

nohup iperf3 --server --port 20003 &> /dev/null &
nohup iperf3 --server --udp --port 20004 &> /dev/null &