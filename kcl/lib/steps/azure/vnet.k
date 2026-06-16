import azure_pipelines.ap.steps

CreateVNet = lambda serviceConnection: str, resourceGroup: str, name: str, addressPrefixes: str, subscription: str, assignee: str = "" -> steps.Step {
    roleAssignmentScript = """
VNET_ID=$(az network vnet show \\
  --resource-group "${resourceGroup}" \\
  --name "${name}" \\
  --subscription "${subscription}" \\
  --query id -o tsv)

az role assignment create \\
  --scope $VNET_ID \\
  --role "Network Contributor" \\
  --assignee-object-id "${assignee}" \\
  --assignee-principal-type ServicePrincipal \\
  --subscription "${subscription}"
""" if assignee else ""
    script = """
az network vnet create \\
  --resource-group "${resourceGroup}" \\
  --name "${name}" \\
  --address-prefixes ${addressPrefixes} \\
  --subscription "${subscription}"
${roleAssignmentScript}"""
    AzCli(serviceConnection, "Create VNet ${name}", script)
}

CreateSubnet = lambda serviceConnection: str, resourceGroup: str, vnetName: str, name: str, addressPrefixes: str, subscription: str -> steps.Step {
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

echo "##vso[task.setvariable variable=${name.upper()}_SUBNET_ID;isOutput=true]$SUBNET_ID"
"""
    AzCli(serviceConnection, "Create subnet ${name}", script, stepName="createSubnet")
}