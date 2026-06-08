import azure_pipelines.ap.steps

CreateVNet = lambda serviceConnection: str, resourceGroup: str, name: str, addressPrefixes: str, subscription: str -> steps.Step {
    script = """
az network vnet create \\
  --resource-group "${resourceGroup}" \\
  --name "${name}" \\
  --address-prefixes ${addressPrefixes} \\
  --subscription "${subscription}"
"""
    AzCli(serviceConnection, "Create VNet ${name}", script)
}

CreateSubnetAndRoleAssignment = lambda serviceConnection: str, resourceGroup: str, vnetName: str, name: str, addressPrefixes: str, subscription: str, assignee: str -> steps.Step {
    script = """
az network vnet subnet create \\
  --resource-group "${resourceGroup}" \\
  --vnet-name "${vnetName}" \\
  --name "${name}" \\
  --address-prefixes ${addressPrefixes} \\
  --subscription "${subscription}"

SUBNET_ID=$(az network vnet subnet show \\
  --resource-group "${resourceGroup}" \\
  --vnet-name "${vnetName}" \\
  --name "${name}" \\
  --subscription "${subscription}" \\
  --query id -o tsv)

az role assignment create \\
  --scope $SUBNET_ID \\
  --role "Network Contributor" \\
  --assignee "${assignee}" \\
  --subscription "${subscription}"

echo "##vso[task.setvariable variable=${name.upper()}_SUBNET_ID]$SUBNET_ID"
"""
    AzCli(serviceConnection, "Create subnet ${name}", script)
}
