#!/bin/bash

sudo perl -pi -e 's/^#?Port 22$/Port 2222/' /etc/ssh/sshd_config
sudo service ssh restart

wget https://telescopetools.z13.web.core.windows.net/packages/network-tools/iperf2/iperf2-2.0.13.mariner.x86_64.rpm
sudo apt-get update
sudo apt install alien -y
sudo alien -i iperf2-2.0.13.mariner.x86_64.rpm