import azure_pipelines.ap.steps

# Match RunClusterLoader2's cutoff. With the default 30-second poll interval, this tolerates
# about 10 minutes of transient API-server failures without allowing an indefinite wait.
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

# Bash function reused by UploadTextFileToJumpbox, RunScriptOnJumpbox,
# and _WaitForClusterLoader2CompletionOnJumpbox.
_RUN_SCRIPT_ON_JUMPBOX_FUNCTION = """
run_script_on_jumpbox() {
  local script_file run_command_output run_command_rc
  script_file=$(mktemp)
  printf 'set -eu\\n' > "$script_file"
  cat >> "$script_file"
  printf '\\necho "__JUMPBOX_SCRIPT_SUCCEEDED__"\\n' >> "$script_file"

  if run_command_output=$(az vm run-command invoke \\
    --resource-group "$2" \\
    --name "$3" \\
    --subscription "$1" \\
    --command-id RunShellScript \\
    --scripts @"$script_file" \\
    --query 'value[0].message' \\
    --output tsv); then
    run_command_rc=0
  else
    run_command_rc=$?
  fi
  rm -f "$script_file"

  if [ "$run_command_rc" -ne 0 ]; then
    printf '%s\\n' "$run_command_output"
    return "$run_command_rc"
  fi
  if ! grep -q '__JUMPBOX_SCRIPT_SUCCEEDED__' <<< "$run_command_output"; then
    printf '%s\\n' "$run_command_output"
    return 1
  fi
  printf '%s\\n' "$run_command_output" | sed '/__JUMPBOX_SCRIPT_SUCCEEDED__/d'
}
"""

UploadTextFileToJumpbox = lambda \
    serviceConnection: str, \
    subscription: str, \
    resourceGroup: str, \
    vmName: str, \
    localFile: str, \
    remoteFile: str \
    -> steps.Step {
    script = """
${_RUN_SCRIPT_ON_JUMPBOX_FUNCTION}

local_file="$(Pipeline.Workspace)/s/${localFile}"
if [ ! -f "$local_file" ]; then
  echo "File not found: $local_file"
  exit 1
fi
if grep -qx '__TELESCOPE_FILE_CONTENT__' "$local_file"; then
  echo "File contains the reserved upload delimiter: __TELESCOPE_FILE_CONTENT__"
  exit 1
fi

if ! run_command_output=$(
  {
cat <<'REMOTE_SCRIPT'
remote_file="${remoteFile}"
mkdir -p "$(dirname "$remote_file")"
cat > "$remote_file" <<'__TELESCOPE_FILE_CONTENT__'
REMOTE_SCRIPT

cat "$local_file"
printf '\n'

cat <<'REMOTE_SCRIPT'
__TELESCOPE_FILE_CONTENT__
test -s "$remote_file"
REMOTE_SCRIPT
  } | run_script_on_jumpbox \\
    "${subscription}" \\
    "${resourceGroup}" \\
    "${vmName}"
); then
  echo "$run_command_output"
  echo "Failed to upload ${localFile} to ${remoteFile} on jumpbox."
  exit 1
fi
echo "$run_command_output"
"""
    AzCli(serviceConnection, "Upload ${localFile} to jumpbox", script)
}

RunScriptOnJumpbox = lambda \
    serviceConnection: str, \
    subscription: str, \
    resourceGroup: str, \
    vmName: str, \
    displayName: str, \
    command: str \
    -> steps.Step {
    script = """
${_RUN_SCRIPT_ON_JUMPBOX_FUNCTION}

if ! run_command_output=$(run_script_on_jumpbox \\
  "${subscription}" \\
  "${resourceGroup}" \\
  "${vmName}" <<'REMOTE_SCRIPT'
${command}
REMOTE_SCRIPT
); then
  echo "$run_command_output"
  echo "Failed to run script on jumpbox."
  exit 1
fi
echo "$run_command_output"
"""
    AzCli(serviceConnection, displayName, script)
}

ApplyManifestOnJumpbox = lambda \
    serviceConnection: str, \
    subscription: str, \
    resourceGroup: str, \
    vmName: str, \
    manifest: str \
    -> [steps.Step] {
    remoteManifest = "/var/tmp/telescope/$(Build.BuildId)/manifest.yaml"
    [
        UploadTextFileToJumpbox(
            serviceConnection,
            subscription,
            resourceGroup,
            vmName,
            manifest,
            remoteManifest
        ),
        RunScriptOnJumpbox(
            serviceConnection,
            subscription,
            resourceGroup,
            vmName,
            "Apply ${manifest} from jumpbox",
            """
export KUBECONFIG=/var/tmp/telescope-kubeconfig
test -s "$KUBECONFIG"
trap 'rm -f "${remoteManifest}"' EXIT
kubectl apply -f "${remoteManifest}"
"""
        ),
    ]
}

_WaitForClusterLoader2CompletionOnJumpbox = lambda \
    serviceConnection: str, \
    subscription: str, \
    resourceGroup: str, \
    vmName: str, \
    pollIntervalSeconds: int = 30 \
    -> steps.Step {
    assert pollIntervalSeconds > 0, "pollIntervalSeconds must be positive"
    script = """
${_RUN_SCRIPT_ON_JUMPBOX_FUNCTION}

# Mirror the polling behavior of RunClusterLoader2.
consecutive_status_errors=0

# Run each status query through the shared run_script_on_jumpbox helper.
while true; do
  if status_message=$(run_script_on_jumpbox \\
    "${subscription}" \\
    "${resourceGroup}" \\
    "${vmName}" <<'REMOTE_SCRIPT'
export KUBECONFIG=/var/tmp/telescope-kubeconfig
kubectl get pods \\
  --namespace="clusterloader2" \\
  --output jsonpath='{range .items[*]}{.status.phase}{"\\n"}{end}'
REMOTE_SCRIPT
  ); then
    echo "$status_message"
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
  else
    echo "$status_message"
    consecutive_status_errors=$((consecutive_status_errors + 1))
    if [ "$consecutive_status_errors" -ge "${MAX_CONSECUTIVE_APISERVER_ERRORS}" ]; then
      echo "Unable to read ClusterLoader2 status after $consecutive_status_errors/${MAX_CONSECUTIVE_APISERVER_ERRORS} consecutive attempts."
      exit 1
    fi
  fi

  sleep ${pollIntervalSeconds}
done
"""
    AzCli(serviceConnection, "Wait for ClusterLoader2 completion from jumpbox", script)
}

RunClusterLoader2OnJumpbox = lambda \
    serviceConnection: str, \
    subscription: str, \
    resourceGroup: str, \
    vmName: str, \
    cl2ConfigFile: str, \
    pollIntervalSeconds: int = 30 \
    -> [steps.Step] {
    remoteCl2ConfigFile = "/var/tmp/telescope/$(Build.BuildId)/cl2.yaml"
    [
        UploadTextFileToJumpbox(
            serviceConnection,
            subscription,
            resourceGroup,
            vmName,
            cl2ConfigFile,
            remoteCl2ConfigFile
        ),
        RunScriptOnJumpbox(
            serviceConnection,
            subscription,
            resourceGroup,
            vmName,
            "Start ClusterLoader2 from jumpbox",
            """
export KUBECONFIG=/var/tmp/telescope-kubeconfig
test -s "$KUBECONFIG"
test -s "${remoteCl2ConfigFile}"
trap 'rm -f "${remoteCl2ConfigFile}"' EXIT
kubectl create namespace "clusterloader2" --dry-run=client -o yaml | kubectl apply -f -
kubectl apply -f "${remoteCl2ConfigFile}"
"""
        ),
        _WaitForClusterLoader2CompletionOnJumpbox(
            serviceConnection,
            subscription,
            resourceGroup,
            vmName,
            pollIntervalSeconds
        ),
    ]
}
