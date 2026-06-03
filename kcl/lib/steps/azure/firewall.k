import azure_pipelines.ap.steps

CreateFirewall = lambda serviceConnection: str, subscription: str, resourceGroup: str, name: str, location: str, vnetName: str, publicIpName: str -> steps.Step {
    script = """
az extension add --name azure-firewall

az network public-ip create \\
  --resource-group "${resourceGroup}" \\
  --name "${publicIpName}" \\
  --sku Standard \\
  --location "${location}" \\
  --subscription "${subscription}"

az network firewall create \\
  --resource-group "${resourceGroup}" \\
  --name "${name}" \\
  --location "${location}" \\
  --enable-dns-proxy true \\
  --subscription "${subscription}"

az network firewall ip-config create \\
  --resource-group "${resourceGroup}" \\
  --firewall-name "${name}" \\
  --name "${name}-ipconfig" \\
  --public-ip-address "${publicIpName}" \\
  --vnet-name "${vnetName}" \\
  --subscription "${subscription}"

FIREWALL_PRIVATE_IP=$(az network firewall show \\
  --resource-group "${resourceGroup}" \\
  --name "${name}" \\
  --subscription "${subscription}" \\
  --query "ipConfigurations[0].privateIPAddress" -o tsv)
echo "##vso[task.setvariable variable=FIREWALL_PRIVATE_IP]$FIREWALL_PRIVATE_IP"
"""
    AzCli(serviceConnection, "Create firewall ${name}", script)
}

AssociateFirewallToSubnet = lambda serviceConnection: str, resourceGroup: str, name: str, location: str, vnetName: str, subnetName: str, firewallIp: str, subscription: str -> steps.Step {
    script = """
az network route-table create \\
  --resource-group "${resourceGroup}" \\
  --name "${name}" \\
  --location "${location}" \\
  --subscription "${subscription}"

az network route-table route create \\
  --resource-group "${resourceGroup}" \\
  --route-table-name "${name}" \\
  --name egress \\
  --address-prefix 0.0.0.0/0 \\
  --next-hop-type VirtualAppliance \\
  --next-hop-ip-address "${firewallIp}" \\
  --subscription "${subscription}"

az network vnet subnet update \\
  --resource-group "${resourceGroup}" \\
  --vnet-name "${vnetName}" \\
  --name "${subnetName}" \\
  --route-table "${name}" \\
  --subscription "${subscription}"
"""
    AzCli(serviceConnection, "Associate firewall ${name} to subnet ${subnetName}", script)
}

UpdateFirewallPolicy = lambda serviceConnection: str, subscription: str, resourceGroup: str, name: str, policyPath: str, location: str -> steps.Step {
    script = """
POLICY_TMP=$(mktemp)
sed 's|"location": "[^"]*"|"location": "${location}"|g' "${policyPath}" > "$POLICY_TMP"
az rest \\
  --method put \\
  --uri "https://management.azure.com/subscriptions/${subscription}/resourceGroups/${resourceGroup}/providers/Microsoft.Network/azureFirewalls/${name}?api-version=2025-05-01" \\
  --headers "Content-Type=application/json" \\
  --body "@$POLICY_TMP"
rm -f "$POLICY_TMP"
"""
    AzCli(serviceConnection, "Update firewall policy ${name}", script)
}
