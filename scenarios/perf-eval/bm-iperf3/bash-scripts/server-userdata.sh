#!/bin/bash

sudo perl -pi -e 's/^#?Port 22$/Port 2222/' /etc/ssh/sshd_config
sudo systemctl restart sshd

sudo iptables -A INPUT -p tcp --dport 2222 -j ACCEPT
sudo iptables -A INPUT -p tcp --dport 20001 -j ACCEPT
sudo iptables -A INPUT -p udp --dport 20002 -j ACCEPT
sudo iptables -A INPUT -p tcp --dport 20002 -j ACCEPT

. /etc/os-release

if [ "$ID" == "ubuntu" ]; then
    sudo apt-get update -y
    sudo apt-get install -y iperf
elif [ "$ID" == "mariner" ]; then
    sudo tdnf install -y binutils
    sudo tdnf install -y gcc gcc-c++ glibc-devel glibc-headers kernel-headers
    wget https://sourceforge.net/projects/iperf2/files/iperf-2.0.13.tar.gz
    tar -xzvf iperf-2.0.13.tar.gz
    cd iperf-2.0.13
    ./configure
    make
    sudo make install
elif [ "$ID" == "amzn" ]; then
    sudo yum update -y
    sudo yum install -y https://dl.fedoraproject.org/pub/epel/epel-release-latest-7.noarch.rpm
    sudo yum --enablerepo=epel install -y iperf
fi

nohup iperf --server --port 20001 &> /dev/null &
nohup iperf --server --udp --port 20002 &> /dev/null &