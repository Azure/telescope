#!/bin/bash

# Change SSH port
sudo perl -pi -e 's/^#?Port 22$/Port 2222/' /etc/ssh/sshd_config
sudo service ssh restart

# Install fio
sudo apt-get update && sudo apt-get install fio -y
fio --version
