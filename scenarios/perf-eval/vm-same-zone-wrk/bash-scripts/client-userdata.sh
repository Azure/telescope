#!/bin/bash

set -e

sudo perl -pi -e 's/^#?Port 22$/Port 2222/' /etc/ssh/sshd_config
sudo service ssh restart

sudo apt-get update
sudo apt-get install build-essential libssl-dev git unzip -y
wget https://github.com/wg/wrk/archive/refs/tags/4.2.0.tar.gz
tar -xzvf 4.2.0.tar.gz
cd wrk-4.2.0
make
sudo cp wrk /usr/local/bin
