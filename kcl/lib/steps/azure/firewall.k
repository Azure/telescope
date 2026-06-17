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

# Merge rule collections from the policy file into the current firewall and PUT it back in one call.
# This handles large rule sets faster than incremental CLI commands (az network firewall policy rule-collection-group)
# and avoids overwriting other firewall properties (e.g. location, ipConfigurations).
if [ -n "${policyPath}" ]; then
  FW_CURRENT=$(mktemp)
  FW_MERGED=$(mktemp)
  az rest \\
    --method get \\
    --uri "https://management.azure.com/subscriptions/${subscription}/resourceGroups/${resourceGroup}/providers/Microsoft.Network/azureFirewalls/${name}?api-version=2025-05-01" \\
    > "$FW_CURRENT"
  jq -s '
    .[0] as $fw | .[1] as $rules |
    $fw
    | .properties.applicationRuleCollections = ($rules.properties.applicationRuleCollections // [])
    | .properties.networkRuleCollections     = ($rules.properties.networkRuleCollections // [])
    | .properties.natRuleCollections         = ($rules.properties.natRuleCollections // [])
  ' "$FW_CURRENT" "${policyPath}" > "$FW_MERGED"
  az rest \\
    --method put \\
    --uri "https://management.azure.com/subscriptions/${subscription}/resourceGroups/${resourceGroup}/providers/Microsoft.Network/azureFirewalls/${name}?api-version=2025-05-01" \\
    --headers "Content-Type=application/json" \\
    --body "@$FW_MERGED"
  rm -f "$FW_CURRENT" "$FW_MERGED"
fi
"""
    AzCli(serviceConnection, "Setup firewall ${name} for subnet ${subnetName}", script)
}

