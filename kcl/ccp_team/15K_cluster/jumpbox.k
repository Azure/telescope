createJumpboxScript = """
cat > /tmp/cloud-init.yaml << 'CLOUDINIT'
#cloud-config
package_update: true
package_upgrade: true
packages:
  - git
  - ca-certificates
  - curl
  - apt-transport-https
  - lsb-release
  - gnupg
runcmd:
  - curl -sL https://aka.ms/InstallAzureCLIDeb | bash
  - wget -q https://go.dev/dl/go1.22.2.linux-amd64.tar.gz -O /tmp/go.tar.gz
  - tar -C /usr/local -xzf /tmp/go.tar.gz
  - echo 'export PATH=$PATH:/usr/local/go/bin' >> /etc/profile.d/go.sh
  - rm /tmp/go.tar.gz
  - curl -LO "https://dl.k8s.io/release/$(curl -Ls https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
  - install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl
  - rm kubectl
CLOUDINIT

az vm create \\
  --resource-group "${RESOURCE_GROUP}" \\
  --name "${JUMPBOX_NAME}" \\
  --image Ubuntu2204 \\
  --size Standard_D16ds_v5 \\
  --vnet-name "${VNET_NAME}" \\
  --subnet jumpbox \\
  --public-ip-address "${JUMPBOX_NAME}-pip" \\
  --admin-username azureuser \\
  --admin-password "$(JUMPBOX_ADMIN_PASSWORD)" \\
  --authentication-type password \\
  --custom-data /tmp/cloud-init.yaml \\
  --subscription "${SUBSCRIPTION_ID}"

az vm open-port \\
  --resource-group "${RESOURCE_GROUP}" \\
  --name "${JUMPBOX_NAME}" \\
  --port 22 \\
  --priority 1001 \\
  --subscription "${SUBSCRIPTION_ID}"

JUMPBOX_PRINCIPAL_ID=$(az vm identity assign \\
  --resource-group "${RESOURCE_GROUP}" \\
  --name "${JUMPBOX_NAME}" \\
  --subscription "${SUBSCRIPTION_ID}" \\
  --query systemAssignedIdentity -o tsv)

RG_ID=$(az group show \\
  --name "${RESOURCE_GROUP}" \\
  --subscription "${SUBSCRIPTION_ID}" \\
  --query id -o tsv)

for role in \\
  "Azure Kubernetes Service Cluster Admin Role" \\
  "Azure Kubernetes Service Cluster User Role" \\
  "Azure Kubernetes Service Contributor Role" \\
  "Azure Kubernetes Service RBAC Cluster Admin"; do
  az role assignment create \\
    --assignee $JUMPBOX_PRINCIPAL_ID \\
    --role "$role" \\
    --scope $RG_ID \\
    --subscription "${SUBSCRIPTION_ID}"
done
"""
