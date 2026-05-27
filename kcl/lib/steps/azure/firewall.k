import azure_pipelines.ap.steps

CreateFirewall = lambda serviceConnection: str, resourceGroup: str, name: str, location: str, vnetName: str, publicIpName: str, subscription: str -> steps.Step {
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

FWPRIVATE_IP=$(az network firewall show \\
  --resource-group "${resourceGroup}" \\
  --name "${name}" \\
  --subscription "${subscription}" \\
  --query "ipConfigurations[0].privateIPAddress" -o tsv)
echo "##vso[task.setvariable variable=FWPRIVATE_IP]$FWPRIVATE_IP"
"""
    AzCli(serviceConnection, "Create firewall ${name}", script)
}

UpdateFirewallPolicy = lambda serviceConnection: str, resourceGroup: str, name: str, subscription: str, policyPath: str, location: str -> steps.Step {
    script = """
POLICY_TMP=$(mktemp)
sed 's|"location": "[^"]*"|"location": "${location}"|g' "${policyPath}" > "$POLICY_TMP"
az rest \\
  --method put \\
  --uri "https://management.azure.com/subscriptions/${subscription}/resourceGroups/${resourceGroup}/providers/Microsoft.Network/azureFirewalls/${name}?api-version=2023-09-01" \\
  --headers "Content-Type=application/json" \\
  --body "@$POLICY_TMP"
rm -f "$POLICY_TMP"
"""
    AzCli(serviceConnection, "Update firewall policy ${name}", script)
}
