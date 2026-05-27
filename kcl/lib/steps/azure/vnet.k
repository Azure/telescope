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

CreateSubnet = lambda serviceConnection: str, resourceGroup: str, vnetName: str, name: str, addressPrefixes: str, subscription: str, exportVar: str = "" -> steps.Step {
    exportScript = """
SUBNET_ID=$(az network vnet subnet show \\
  --resource-group "${resourceGroup}" \\
  --vnet-name "${vnetName}" \\
  --name "${name}" \\
  --subscription "${subscription}" \\
  --query id -o tsv)
echo "##vso[task.setvariable variable=${exportVar}]$SUBNET_ID"
""" if exportVar else ""
    script = """
az network vnet subnet create \\
  --resource-group "${resourceGroup}" \\
  --vnet-name "${vnetName}" \\
  --name "${name}" \\
  --address-prefixes ${addressPrefixes} \\
  --subscription "${subscription}"
""" + exportScript
    AzCli(serviceConnection, "Create subnet ${name}", script)
}
