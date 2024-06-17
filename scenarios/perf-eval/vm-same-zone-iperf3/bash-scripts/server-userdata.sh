#!/bin/bash

sudo perl -pi -e 's/^#?Port 22$/Port 2222/' /etc/ssh/sshd_config
sudo service ssh restart

sudo apt-get update && sudo apt-get install iperf3 -y

# set up tcp listener
nohup iperf3 --server --port 20003 &> /dev/null &
# set up udp listener
nohup iperf3 --server --port 20004 &> /dev/null &