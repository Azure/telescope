import azure_pipelines.ap.steps

# Default cloud-init for an AKS-friendly jumpbox: installs Azure CLI, kubectl, and the Go toolchain.
DEFAULT_JUMPBOX_CLOUD_INIT = """#cloud-config
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
"""

# Default role assignments for the jumpbox managed identity, keyed by role name.
# An empty-string scope means "the resource group the jumpbox is created in" (resolved at run time).
# Cluster Admin Role grants listClusterAdminCredential (admin kubeconfig -> full kube-apiserver access);
# Contributor Role grants AKS management ops (scale, nodepool, upgrade, etc.) plus listClusterUserCredential.
# Together these subsume Cluster User Role and RBAC Cluster Admin for our use cases.
DEFAULT_AKS_JUMPBOX_ROLES = {
    "Azure Kubernetes Service Cluster Admin Role" = ""
    "Azure Kubernetes Service Contributor Role" = ""
}

# CreateJumpbox provisions a Linux jumpbox VM in an existing VNet/subnet, opens SSH, enables a system-assigned
# managed identity, and (optionally) assigns roles to that identity.
#
# `roles` is a {role: scope} map. An empty-string scope falls back to the jumpbox's resource group id.
#
# The admin password is read from a pipeline secret variable (default: JUMPBOX_ADMIN_PASSWORD); the caller
# must wire that variable up via a variable group or pipeline secret.
CreateJumpbox = lambda \
    serviceConnection: str, \
    subscription: str, \
    resourceGroup: str, \
    name: str, \
    vnetName: str, \
    subnetName: str = "jumpbox", \
    adminUsername: str = "azureuser", \
    adminPasswordVar: str = "JUMPBOX_ADMIN_PASSWORD", \
    vmSize: str = "Standard_D16ds_v5", \
    image: str = "Ubuntu2204", \
    cloudInit: str = DEFAULT_JUMPBOX_CLOUD_INIT, \
    roles: {str:str} = DEFAULT_AKS_JUMPBOX_ROLES \
    -> steps.Step {
    rgScopeExpr = "$(az group show --name \"${resourceGroup}\" --subscription \"${subscription}\" --query id -o tsv)"
    roleAssignments = "\n".join([
        """az role assignment create \\
  --assignee "$JUMPBOX_PRINCIPAL_ID" \\
  --role "${role}" \\
  --scope "${roles[role] if roles[role] else rgScopeExpr}" \\
  --subscription "${subscription}"
""" for role in roles
    ])

    script = """
cat > /tmp/cloud-init.yaml << 'CLOUDINIT'
${cloudInit}CLOUDINIT

az vm create \\
  --resource-group "${resourceGroup}" \\
  --name "${name}" \\
  --image ${image} \\
  --size ${vmSize} \\
  --vnet-name "${vnetName}" \\
  --subnet "${subnetName}" \\
  --public-ip-address "${name}-pip" \\
  --admin-username "${adminUsername}" \\
  --admin-password "$(${adminPasswordVar})" \\
  --authentication-type password \\
  --custom-data /tmp/cloud-init.yaml \\
  --subscription "${subscription}"

az vm open-port \\
  --resource-group "${resourceGroup}" \\
  --name "${name}" \\
  --port 22 \\
  --priority 1001 \\
  --subscription "${subscription}"

JUMPBOX_PRINCIPAL_ID=$(az vm identity assign \\
  --resource-group "${resourceGroup}" \\
  --name "${name}" \\
  --subscription "${subscription}" \\
  --query systemAssignedIdentity -o tsv)
${roleAssignments}"""
    AzCli(serviceConnection, "Create jumpbox ${name}", script)
}
