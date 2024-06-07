#!/bin/bash

sudo perl -pi -e 's/^#?Port 22$/Port 2222/' /etc/ssh/sshd_config
sudo systemctl restart sshd



. /etc/os-release

if [ "$ID" == "ubuntu" ]; then
    sudo apt-get update -y
    sudo apt-get install -y iperf
elif [ "$ID" == "mariner" ]; then
    sudo iptables -A INPUT -p tcp --dport 2222 -j ACCEPT
    
    wget https://telescopetools.blob.core.windows.net/packages/network-tools/iperf2/iperf2-2.0.13.x86_64.rpm
    sudo tdnf install -y iperf2-2.0.13.x86_64.rpm
elif [ "$ID" == "amzn" ]; then
    sudo yum update -y
    sudo yum install -y https://dl.fedoraproject.org/pub/epel/epel-release-latest-7.noarch.rpm
    sudo yum --enablerepo=epel install -y iperf
fi
