#!/bin/bash

# Change SSH port
sudo perl -pi -e 's/^#?Port 22$/Port 2222/' /etc/ssh/sshd_config
sudo service ssh restart

# Install fio
sudo apt-get update && sudo apt-get install fio -y
fio --version

# install blobfuse2
sudo wget https://packages.microsoft.com/config/ubuntu/22.04/packages-microsoft-prod.deb
sudo dpkg -i packages-microsoft-prod.deb
sudo apt-get update
sudo apt-get install libfuse3-dev fuse3 -y
sudo apt-get install blobfuse2 -y

# install s3fs
sudo apt-get install s3fs -y