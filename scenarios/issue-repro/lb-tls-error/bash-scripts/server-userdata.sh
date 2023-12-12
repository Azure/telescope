#!/bin/bash

set -e

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

# Pull image
docker pull -q telescope.azurecr.io/issue-repro/slb-eof-error-server:v1.0.9
docker run -d --name server -e READ_HEADER_TIMEOUT=32 -p 4443:4443 -p 8080:8080 telescope.azurecr.io/issue-repro/slb-eof-error-server:v1.0.9