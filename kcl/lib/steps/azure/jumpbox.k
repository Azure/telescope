import azure_pipelines.ap.steps

MAX_CONSECUTIVE_APISERVER_ERRORS = 20

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

# RoleAssignment describes a single Azure RBAC role to grant to the jumpbox managed identity.
# `scope` is the full Azure resource id at which the role is granted; an empty string falls back
# to the jumpbox's resource group id (resolved at run time).
schema RoleAssignment:
    role: str
    scope: str = ""

# Default role assignments for the jumpbox managed identity.
# Cluster Admin Role grants listClusterAdminCredential (admin kubeconfig -> full kube-apiserver access);
# Contributor Role grants AKS management ops (scale, nodepool, upgrade, etc.) plus listClusterUserCredential.
# Together these subsume Cluster User Role and RBAC Cluster Admin for our use cases.
DEFAULT_AKS_JUMPBOX_ROLES = [
    RoleAssignment {role = "Azure Kubernetes Service Cluster Admin Role"}
    RoleAssignment {role = "Azure Kubernetes Service Contributor Role"}
]

# CreateJumpbox provisions a Linux jumpbox VM in an existing VNet/subnet, enables a system-assigned
# managed identity, and (optionally) assigns roles to that identity.
#
# Remote access is expected to use `az vm run-command invoke` (ARM -> VM Guest Agent), so no inbound
# SSH port is opened. `--generate-ssh-keys` is kept only to satisfy `az vm create`'s Linux auth
# requirement; the generated key on the agent is unused.
CreateJumpbox = lambda \
    serviceConnection: str, \
    subscription: str, \
    resourceGroup: str, \
    name: str, \
    vnetName: str, \
    subnetName: str = "jumpbox", \
    adminUsername: str = "azureuser", \
    vmSize: str = "Standard_D16ds_v5", \
    image: str = "Ubuntu2204", \
    cloudInit: str = DEFAULT_JUMPBOX_CLOUD_INIT, \
    roles: [RoleAssignment] = DEFAULT_AKS_JUMPBOX_ROLES \
    -> steps.Step {
    rgScopeExpr = "$(az group show --name \"${resourceGroup}\" --subscription \"${subscription}\" --query id -o tsv)"
    roleAssignments = "\n".join([
        """az role assignment create \\
  --assignee "$JUMPBOX_PRINCIPAL_ID" \\
  --role "${r.role}" \\
  --scope "${r.scope if r.scope else rgScopeExpr}" \\
  --subscription "${subscription}"
""" for r in roles
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
  --generate-ssh-keys \\
  --custom-data /tmp/cloud-init.yaml \\
  --subscription "${subscription}"

JUMPBOX_PRINCIPAL_ID=$(az vm identity assign \\
  --resource-group "${resourceGroup}" \\
  --name "${name}" \\
  --subscription "${subscription}" \\
  --query systemAssignedIdentity -o tsv)
${roleAssignments}"""
    AzCli(serviceConnection, "Create jumpbox ${name}", script)
}

ApplyManifestOnJumpbox = lambda \
    serviceConnection: str, \
    subscription: str, \
    resourceGroup: str, \
    vmName: str, \
    manifest: str \
    -> steps.Step {
    script = """
work_dir=$(mktemp -d)
trap 'rm -rf "$work_dir"' EXIT

manifest_path="$(Pipeline.Workspace)/s/${manifest}"
if [ ! -f "$manifest_path" ]; then
  echo "Kubernetes manifest not found: $manifest_path"
  exit 1
fi
manifest_size=$(wc -c < "$manifest_path" | tr -d ' ')
if [ "$manifest_size" -gt 45000 ]; then
  echo "Kubernetes manifest is too large for az vm run-command invoke: $manifest_size bytes."
  exit 1
fi

remote_script="$work_dir/apply-manifest.sh"
cat > "$remote_script" <<'REMOTE_SCRIPT'
set -eu
export KUBECONFIG=/var/tmp/telescope-kubeconfig
test -s "$KUBECONFIG"
kubectl apply -f - <<'MANIFEST'
REMOTE_SCRIPT
cat "$manifest_path" >> "$remote_script"
cat >> "$remote_script" <<'REMOTE_SCRIPT'
MANIFEST
echo "__MANIFEST_APPLIED__"
REMOTE_SCRIPT

run_command_output=$(az vm run-command invoke \\
  --resource-group "${resourceGroup}" \\
  --name "${vmName}" \\
  --subscription "${subscription}" \\
  --command-id RunShellScript \\
  --scripts @"$remote_script" \\
  --query 'value[0].message' \\
  --output tsv)
echo "$run_command_output"
if ! grep -q '__MANIFEST_APPLIED__' <<< "$run_command_output"; then
  echo "Failed to apply ${manifest} from jumpbox."
  exit 1
fi
"""
    AzCli(serviceConnection, "Apply ${manifest} from jumpbox", script)
}

RunClusterLoader2OnJumpbox = lambda \
    serviceConnection: str, \
    subscription: str, \
    resourceGroup: str, \
    vmName: str, \
    cl2ConfigFile: str, \
    pollIntervalSeconds: int = 30 \
    -> steps.Step {
    assert pollIntervalSeconds > 0, "pollIntervalSeconds must be positive"
    script = """
work_dir=$(mktemp -d)
trap 'rm -rf "$work_dir"' EXIT

invoke_jumpbox() {
  script_file=$1
  az vm run-command invoke \\
    --resource-group "${resourceGroup}" \\
    --name "${vmName}" \\
    --subscription "${subscription}" \\
    --command-id RunShellScript \\
    --scripts @"$script_file" \\
    --query 'value[0].message' \\
    --output tsv
}

cl2_config_file_path="$(Pipeline.Workspace)/s/${cl2ConfigFile}"
if [ ! -f "$cl2_config_file_path" ]; then
  echo "ClusterLoader2 config file not found: $cl2_config_file_path"
  exit 1
fi
cl2_config_file_size=$(wc -c < "$cl2_config_file_path" | tr -d ' ')
if [ "$cl2_config_file_size" -gt 45000 ]; then
  echo "ClusterLoader2 config file is too large for az vm run-command invoke: $cl2_config_file_size bytes."
  exit 1
fi

launch_script="$work_dir/launch-cl2.sh"
cat > "$launch_script" <<'REMOTE_SCRIPT'
set -eu
export KUBECONFIG=/var/tmp/telescope-kubeconfig
test -s "$KUBECONFIG"
kubectl create namespace "clusterloader2" --dry-run=client -o yaml | kubectl apply -f -
kubectl apply -f - <<'MANIFEST'
REMOTE_SCRIPT
cat "$cl2_config_file_path" >> "$launch_script"
cat >> "$launch_script" <<'REMOTE_SCRIPT'
MANIFEST
echo "__CL2_STARTED__"
REMOTE_SCRIPT

echo "Starting ClusterLoader2 from jumpbox ${vmName}..."
launch_message=$(invoke_jumpbox "$launch_script")
echo "$launch_message"
if ! grep -q '__CL2_STARTED__' <<< "$launch_message"; then
  echo "Failed to start ClusterLoader2 from jumpbox."
  exit 1
fi

status_script="$work_dir/cl2-status.sh"
cat > "$status_script" <<'REMOTE_SCRIPT'
set -eu
export KUBECONFIG=/var/tmp/telescope-kubeconfig
kubectl get pods \\
  --namespace="clusterloader2" \\
  --output jsonpath='{range .items[*]}{.status.phase}{"\\n"}{end}'
REMOTE_SCRIPT

# Mirror the polling behavior of RunClusterLoader2.
consecutive_status_errors=0
while true; do
  set +e
  status_message=$(invoke_jumpbox "$status_script")
  status_rc=$?
  set -e
  echo "$status_message"
  if [ "$status_rc" -ne 0 ]; then
    consecutive_status_errors=$((consecutive_status_errors + 1))
    if [ "$consecutive_status_errors" -ge "${MAX_CONSECUTIVE_APISERVER_ERRORS}" ]; then
      echo "Unable to read ClusterLoader2 status after $consecutive_status_errors/${MAX_CONSECUTIVE_APISERVER_ERRORS} consecutive attempts."
      exit 1
    fi
  else
    consecutive_status_errors=0
    phases=$(printf '%s\\n' "$status_message" | tr -d '\\r' | grep -E '^(Pending|Running|Succeeded|Failed|Unknown)$' || true)
    total=0
    terminal=0

    if [ -n "$phases" ]; then
      while IFS= read -r phase; do
        if [ -z "$phase" ]; then
          continue
        fi

        total=$((total + 1))
        if [ "$phase" = "Succeeded" ] || [ "$phase" = "Failed" ]; then
          terminal=$((terminal + 1))
        fi
      done <<< "$phases"
    fi

    if [ "$total" -gt 0 ] && [ "$terminal" -eq "$total" ]; then
      echo "All cl2 pods reached terminal state (Succeeded or Failed)"
      break
    fi
  fi

  sleep ${pollIntervalSeconds}
done
"""
    AzCli(serviceConnection, "Run ClusterLoader2 from jumpbox", script)
}
