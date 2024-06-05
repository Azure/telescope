#!/bin/bash
set -e

sudo perl -pi -e 's/^#?Port 22$/Port 2222/' /etc/ssh/sshd_config
sudo service ssh restart

sudo apt-get -qq update
sudo apt-get -qq install gcc

mkdir /home/ubuntu/ncps
chown -R ubuntu:ubuntu /home/ubuntu/ncps

sudo bash -c 'cat >> /etc/security/limits.conf' << EOF
* soft nofile 1048575
* hard nofile 1048575
EOF
