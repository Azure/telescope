#!/bin/bash

sudo perl -pi -e 's/^#?Port 22$/Port 2222/' /etc/ssh/sshd_config
sudo systemctl restart sshd

. /etc/os-release

if [ "$ID" == "ubuntu" ]; then
    sudo apt-get update -y
    sudo apt-get install -y iperf
elif [ "$ID" == "mariner" ]; then
    sudo iptables -A INPUT -p tcp --dport 2222 -j ACCEPT
    sudo iptables -A INPUT -p tcp --dport 20001 -j ACCEPT
    sudo iptables -A INPUT -p udp --dport 20002 -j ACCEPT
    sudo iptables -A INPUT -p tcp --dport 20002 -j ACCEPT
    
    wget https://telescopetools.z13.web.core.windows.net/packages/network-tools/iperf2/iperf2-2.0.13.mariner.x86_64.rpm
    sudo tdnf install -y iperf2-2.0.13.mariner.x86_64.rpm
elif [ "$ID" == "amzn" ]; then
    sudo yum update -y
    sudo yum install -y https://dl.fedoraproject.org/pub/epel/epel-release-latest-7.noarch.rpm
    sudo yum --enablerepo=epel install -y iperf
fi

nohup iperf --server --port 20001 &> /dev/null &
nohup iperf --server --udp --port 20002 &> /dev/null &