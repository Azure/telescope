#cloud-config
package_update: true
package_upgrade: true
packages:
  - python3
  - python3-pip
  - python3-venv
  - python3-virtualenv
  - jq
  - git
  - apt-transport-https
  - ca-certificates
  - curl
  - gnupg
  - lsb-release
  - unzip
  - docker.io
runcmd:
  # Wait for cloud-init packages to be fully installed
  - sleep 60
  # Enable Docker (installed via apt package manager)
  - systemctl enable docker
  - systemctl start docker
  - usermod -aG docker azureuser
  # Install Azure CLI via Microsoft's official apt repository with GPG verification
  - mkdir -p /etc/apt/keyrings
  - bash -c "curl -sLS https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor -o /etc/apt/keyrings/microsoft.gpg"
  - chmod go+r /etc/apt/keyrings/microsoft.gpg
  - bash -c 'echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/microsoft.gpg] https://packages.microsoft.com/repos/azure-cli/ $(lsb_release -cs) main" > /etc/apt/sources.list.d/azure-cli.list'
  - bash -c "apt-get update && apt-get install -y azure-cli"
  - bash -c "az extension add --name aks-preview || true"
  # Install kubectl with SHA256 checksum verification
  - bash -c 'cd /tmp && KUBECTL_VERSION=$(curl -sSfL https://dl.k8s.io/release/stable.txt) && curl -sSfLO "https://dl.k8s.io/release/$KUBECTL_VERSION/bin/linux/amd64/kubectl" && curl -sSfLO "https://dl.k8s.io/release/$KUBECTL_VERSION/bin/linux/amd64/kubectl.sha256" && echo "$(cat kubectl.sha256)  kubectl" | sha256sum --check && install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl && rm -f kubectl kubectl.sha256'
  # Install kubelogin via az aks install-cli (official method)
  - bash -c "az aks install-cli --only-show-errors || true"
  # Install Helm with checksum verification
  - bash -c 'cd /tmp && HELM_VERSION=$(curl -sSfL https://api.github.com/repos/helm/helm/releases/latest | jq -r .tag_name) && curl -sSfLO "https://get.helm.sh/helm-$HELM_VERSION-linux-amd64.tar.gz" && curl -sSfLO "https://get.helm.sh/helm-$HELM_VERSION-linux-amd64.tar.gz.sha256sum" && sha256sum -c helm-$HELM_VERSION-linux-amd64.tar.gz.sha256sum && tar -zxvf helm-$HELM_VERSION-linux-amd64.tar.gz && install -o root -g root -m 0755 linux-amd64/helm /usr/local/bin/helm && rm -rf helm-$HELM_VERSION-linux-amd64.tar.gz helm-$HELM_VERSION-linux-amd64.tar.gz.sha256sum linux-amd64'
