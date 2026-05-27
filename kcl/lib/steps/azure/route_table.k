import azure_pipelines.ap.steps

CreateRouteTable = lambda serviceConnection: str, resourceGroup: str, name: str, location: str, subscription: str -> steps.Step {
    script = """
az network route-table create \\
  --resource-group "${resourceGroup}" \\
  --name "${name}" \\
  --location "${location}" \\
  --subscription "${subscription}"
"""
    AzCli(serviceConnection, "Create route table ${name}", script)
}

CreateRoute = lambda serviceConnection: str, resourceGroup: str, routeTableName: str, name: str, addressPrefix: str, nextHopType: str, nextHopIp: str, subscription: str -> steps.Step {
    script = """
az network route-table route create \\
  --resource-group "${resourceGroup}" \\
  --route-table-name "${routeTableName}" \\
  --name "${name}" \\
  --address-prefix ${addressPrefix} \\
  --next-hop-type ${nextHopType} \\
  --next-hop-ip-address "${nextHopIp}" \\
  --subscription "${subscription}"
"""
    AzCli(serviceConnection, "Create route ${name} in ${routeTableName}", script)
}


AssociateRouteTable = lambda serviceConnection: str, resourceGroup: str, vnetName: str, subnetName: str, routeTableName: str, subscription: str -> steps.Step {
    script = """
az network vnet subnet update \\
  --resource-group "${resourceGroup}" \\
  --vnet-name "${vnetName}" \\
  --name "${subnetName}" \\
  --route-table "${routeTableName}" \\
  --subscription "${subscription}"
"""
    AzCli(serviceConnection, "Associate route table ${routeTableName} with subnet ${subnetName}", script)
}
