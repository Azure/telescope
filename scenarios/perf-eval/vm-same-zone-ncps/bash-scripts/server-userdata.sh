#!/bin/bash
set -e

sudo perl -pi -e 's/^#?Port 22$/Port 2222/' /etc/ssh/sshd_config
sudo service ssh restart

sudo apt-get -qq update
sudo apt-get -qq install gcc

mkdir /home/ubuntu/ncps