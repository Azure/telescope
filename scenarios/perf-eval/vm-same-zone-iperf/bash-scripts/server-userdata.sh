#!/bin/bash

sudo perl -pi -e 's/^#?Port 22$/Port 2222/' /etc/ssh/sshd_config
sudo service ssh restart

sudo apt-get update && sudo apt-get install iperf -y

nohup iperf --server --port 20001 &> /dev/null &
nohup iperf --server --udp --port 20002 &> /dev/null &