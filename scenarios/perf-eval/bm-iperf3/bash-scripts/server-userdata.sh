#!/bin/bash

sudo perl -pi -e 's/^#?Port 22$/Port 2222/' /etc/ssh/sshd_config
sudo systemctl restart sshd

sudo iptables -A INPUT -p tcp --dport 2222 -j ACCEPT
sudo iptables -A INPUT -p tcp --dport 20001 -j ACCEPT
sudo iptables -A INPUT -p udp --dport 20002 -j ACCEPT
sudo iptables -A INPUT -p tcp --dport 20002 -j ACCEPT

sudo tdnf install iperf3 -y

nohup iperf3 --server --port 20001 &> /dev/null &
nohup iperf3 --server --port 20002 &> /dev/null &