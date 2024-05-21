#!/bin/bash
set -e

sudo perl -pi -e 's/^#?Port 22$/Port 2222/' /etc/ssh/sshd_config
sudo service ssh restart

# Install nginx
sudo apt-get update && sudo apt-get install nginx -y
nginx -v
