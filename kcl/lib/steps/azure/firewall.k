import azure_pipelines.ap.steps

SetupFirewallForSubnet = lambda serviceConnection: str, subscription: str, resourceGroup: str, location: str, name: str, vnetName: str, subnetName: str, policyPath: str = "" -> steps.Step {
    script = """
az extension add --name azure-firewall

az network public-ip create \\
  --resource-group "${resourceGroup}" \\
  --name "${name}-pip" \\
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
  --public-ip-address "${name}-pip" \\
  --vnet-name "${vnetName}" \\
  --subscription "${subscription}"

FIREWALL_PRIVATE_IP=$(az network firewall show \\
  --resource-group "${resourceGroup}" \\
  --name "${name}" \\
  --subscription "${subscription}" \\
  --query "ipConfigurations[0].privateIPAddress" -o tsv)
echo "##vso[task.setvariable variable=FIREWALL_PRIVATE_IP]$FIREWALL_PRIVATE_IP"

az network route-table create \\
  --resource-group "${resourceGroup}" \\
  --name "${name}-rt" \\
  --location "${location}" \\
  --subscription "${subscription}"

az network route-table route create \\
  --resource-group "${resourceGroup}" \\
  --route-table-name "${name}-rt" \\
  --name egress \\
  --address-prefix 0.0.0.0/0 \\
  --next-hop-type VirtualAppliance \\
  --next-hop-ip-address "$FIREWALL_PRIVATE_IP" \\
  --subscription "${subscription}"

az network vnet subnet update \\
  --resource-group "${resourceGroup}" \\
  --vnet-name "${vnetName}" \\
  --name "${subnetName}" \\
  --route-table "${name}-rt" \\
  --subscription "${subscription}"

# Use az rest PUT to apply the full firewall policy in one call — handles large rule sets
# and is significantly faster than incremental CLI commands (az network firewall policy rule-collection-group)
if [ -n "${policyPath}" ]; then
  POLICY_TMP=$(mktemp)
  sed 's|"location": "[^"]*"|"location": "${location}"|g' "${policyPath}" > "$POLICY_TMP"
  az rest \\
    --method put \\
    --uri "https://management.azure.com/subscriptions/${subscription}/resourceGroups/${resourceGroup}/providers/Microsoft.Network/azureFirewalls/${name}?api-version=2025-05-01" \\
    --headers "Content-Type=application/json" \\
    --body "@$POLICY_TMP"
  rm -f "$POLICY_TMP"
fi
"""
    AzCli(serviceConnection, "Setup firewall ${name} for subnet ${subnetName}", script)
}

