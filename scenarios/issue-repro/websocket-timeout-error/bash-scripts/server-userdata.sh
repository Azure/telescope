#!/bin/bash

set -e

sudo perl -pi -e 's/^#?Port 22$/Port 2222/' /etc/ssh/sshd_config
sudo service ssh restart

sudo apt-get -qq update
sudo apt-get -qq install ca-certificates curl gnupg

sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --yes --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

# Add the repository to apt sources:
echo "deb [arch="$(dpkg --print-architecture)" signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  "$(. /etc/os-release && echo "$VERSION_CODENAME")" stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# Install the latest version
sudo apt-get -qq update
sudo apt-get -qq install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Verify docker has been installed
docker --version

sudo chmod 666 /var/run/docker.sock

# Pull image
docker pull -q telescope.azurecr.io/issue-repro/websocket-server:v1.2.2
docker run -d --name server -p 4443:4443 -p 8080:8080 telescope.azurecr.io/issue-repro/websocket-server:v1.2.2