#!/bin/bash

sudo sysctl -w net.core.rmem_max=1048576
sudo sysctl -w net.core.rmem_default=1048576

sudo perl -pi -e 's/^#?Port 22$/Port 2222/' /etc/ssh/sshd_config
sudo service ssh restart

wget https://telescopetools.z13.web.core.windows.net/packages/network-tools/iperf2/iperf2-2.0.13.mariner.x86_64.rpm
sudo apt-get update
sudo apt install alien -y
sudo alien -i iperf2-2.0.13.mariner.x86_64.rpm

nohup iperf --server --port 20001 &> /dev/null &
nohup iperf --server --udp --port 20002 &> /dev/null &