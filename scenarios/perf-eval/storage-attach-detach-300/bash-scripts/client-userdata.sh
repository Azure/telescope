#!/bin/bash

# Change SSH port
sudo perl -pi -e 's/^#?Port 22$/Port 2222/' /etc/ssh/sshd_config
sudo service ssh restart

# Install curl
sudo apt-get update && sudo apt install curl -y

# Install kubectl
sudo curl -LO https://storage.googleapis.com/kubernetes-release/release/v1.18.0/bin/linux/amd64/kubectl && sudo chmod +x ./kubectl && sudo mv ./kubectl /usr/local/bin/kubectl && sudo kubectl version --client