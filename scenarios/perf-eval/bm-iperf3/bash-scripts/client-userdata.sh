#!/bin/bash

sudo perl -pi -e 's/^#?Port 22$/Port 2222/' /etc/ssh/sshd_config
sudo systemctl restart sshd

sudo iptables -A INPUT -p tcp --dport 2222 -j ACCEPT

sudo tdnf install iperf3 -y