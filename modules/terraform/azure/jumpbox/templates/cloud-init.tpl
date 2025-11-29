#cloud-config
package_update: true
package_upgrade: true
packages:
  - python3
  - python3-pip
  - jq
  - git
  - apt-transport-https
  - ca-certificates
  - curl
  - gnupg
  - lsb-release
  - unzip
runcmd:
  - bash -c "sleep 20"
  # Install Docker
  - bash -c "curl -fsSL https://get.docker.com | sh"
  - bash -c "systemctl enable docker && systemctl start docker"
  - bash -c "usermod -aG docker azureuser"
  # Install Azure CLI
  - bash -c "curl -sL https://aka.ms/InstallAzureCLIDeb | bash || exit 1"
  - bash -c "which az || exit 1"
  - bash -c "az extension add --name aks-preview || true"
  # Install kubectl
  - bash -c 'KUBECTL_VERSION=$(curl -sSfL https://dl.k8s.io/release/stable.txt) && curl -sSfL "https://dl.k8s.io/release/$${KUBECTL_VERSION}/bin/linux/amd64/kubectl" -o /usr/local/bin/kubectl && chmod +x /usr/local/bin/kubectl'
  # Install Helm
  - bash -c "curl -sSfL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash"
  # Install Python tools
  - bash -c "pip3 install --upgrade pip --break-system-packages"
  - bash -c "pip3 install --upgrade virtualenv --break-system-packages"
