#!/bin/bash
set -e

sudo perl -pi -e 's/^#?Port 22$/Port 2222/' /etc/ssh/sshd_config
sudo service ssh restart

sudo apt-get -qq update
sudo apt-get -qq install gcc

sudo bash -c 'cat >> /etc/security/limits.conf' << EOF
* soft nofile 1048575
* hard nofile 1048575
EOF

wget https://telescopetools.z13.web.core.windows.net/packages/network-tools/ncps/ncps_1.1.tar.gz
tar -xzf ncps_1.1.tar.gz
cp ncps/ncps /bin/ncps
nohup ncps -s &> /dev/null &
