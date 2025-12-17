LOCATION="eastus2"
RG=stretch-rg
CLUSTER=cni-stretch
VNET_NAME="aks-vnet"
SUBNET="aks-subnet"

TENANT_ID="72f988bf-86f1-41af-91ab-2d7cd011db47"
AAD_ADMIN_GROUP_ID="8a5603a8-2c60-49ab-bc28-a989b91e187d"

create_cluster() {
    az group create -n ${RG} -l $LOCATION --tags "SkipAKSCluster=1" "SkipASB_Audit=true" "SkipLinuxAzSecPack=true"

    az network vnet create --resource-group $RG --location $LOCATION --name $VNET_NAME --address-prefixes 10.0.0.0/8 -o none
    az network vnet subnet create --resource-group $RG --vnet-name $VNET_NAME --name $SUBNET --address-prefixes 10.128.0.0/10 -o none

    vnet_id=$(az network vnet show --resource-group $RG --name $VNET_NAME --query id -o tsv)
    subnet_id=$(az network vnet subnet show --resource-group $RG --vnet-name $VNET_NAME --name $SUBNET --query id -o tsv)

    # Create user-assigned managed identity
    IDENTITY_NAME="${CLUSTER}-identity"
    az identity create --name $IDENTITY_NAME --resource-group $RG --location $LOCATION

    # Get the identity resource ID and principal ID
    identity_id=$(az identity show --name $IDENTITY_NAME --resource-group $RG --query id -o tsv)
    identity_principal_id=$(az identity show --name $IDENTITY_NAME --resource-group $RG --query principalId -o tsv)

    # Assign Network Contributor role to the identity to vnet
    az role assignment create --assignee $identity_principal_id --role "Network Contributor" --scope $vnet_id

    az aks create \
        --resource-group "${RG}" \
        --name "${CLUSTER}" \
        --location $LOCATION \
        --kubernetes-version 1.33.0 \
        --tier Standard \
        --node-count 3 \
        --nodepool-name system \
        --vm-set-type VirtualMachineScaleSets \
        --node-vm-size Standard_D8ds_v6 \
        --os-sku Ubuntu2404 \
        --network-plugin none \
        --vnet-subnet-id $subnet_id \
        --enable-managed-identity \
        --assign-identity $identity_id \
        --enable-aad \
        --enable-azure-rbac \
        --aad-admin-group-object-ids $AAD_ADMIN_GROUP_ID \
        --aad-tenant-id $TENANT_ID
}

update_aks_vmss() {
    node_rg=$(az aks show --resource-group $RG --name $CLUSTER --query nodeResourceGroup -o tsv)
    vmss_name=$(az vmss list --resource-group $node_rg --query "[0].name" -o tsv)

    echo "Updating VMSS: $vmss_name in resource group: $node_rg"
    subnet_id=$(az network vnet subnet show --resource-group $RG --vnet-name $VNET_NAME --name $SUBNET --query id -o tsv)
    vmss_json=$(az vmss show --resource-group $node_rg --name $vmss_name)
    vmss_location=$(echo "$vmss_json" | jq -r '.location')
    
    # Get network interface configuration (az vmss show uses camelCase in properties)
    nic_config=$(echo "$vmss_json" | jq '.virtualMachineProfile.networkProfile.networkInterfaceConfigurations[0]')
    nic_name=$(echo "$nic_config" | jq -r '.name')
    nic_primary=$(echo "$nic_config" | jq -r '.primary')
    nic_accel=$(echo "$nic_config" | jq -r '.enableAcceleratedNetworking')
    nic_ipfwd=$(echo "$nic_config" | jq -r '.enableIpForwarding')
    
    # Get existing IP configurations (these are at the root level, not nested under .properties in az vmss show)
    existing_ipconfigs=$(echo "$nic_config" | jq -c '.ipConfigurations')
    
    echo "Found NIC: $nic_name with $(echo "$existing_ipconfigs" | jq 'length') IP configuration(s)"
    
    # Transform existing IP configs to ARM format (az vmss show has flat structure, ARM needs .properties)
    transformed_ipconfigs=$(echo "$existing_ipconfigs" | jq '[.[] | {
        name: .name,
        properties: {
            loadBalancerBackendAddressPools: .loadBalancerBackendAddressPools,
            primary: .primary,
            subnet: {
                id: .subnet.id
            },
            privateIPAddressVersion: .privateIpAddressVersion
        }
    }]')

    ipvlan_config=$(echo "$existing_ipconfigs" | jq -c '.[] | select(.name == "ipvlan")')
    if [[ -n "$ipvlan_config" ]]; then
        echo "IPvlan IP configuration already exists in VMSS"        
        # Append privateIPAddressPrefixLength to the existing ipvlan config
        updated_ipvlan_config=$(echo "$ipvlan_config" | jq '{
            name: .name,
            properties: {
                primary: .primary,
                subnet: {
                    id: .subnet.id
                },
                privateIPAddressVersion: .privateIpAddressVersion,
                privateIPAddressPrefixLength: "28"
            }
        }')
        
        # Replace the existing ipvlan config with the updated one
        updated_ipconfigs=$(echo "$transformed_ipconfigs" | jq --argjson updated "$updated_ipvlan_config" '
            map(if .name == "ipvlan" then $updated else . end)
        ')
        # echo "Updated config: $updated_ipconfigs"
    else
        echo "IPvlan IP configuration not found. Proceeding to add it."
        # Create new secondary IP config
        new_ipconfig=$(jq -n \
            --arg subnet_id "$subnet_id" \
            '{
                name: "ipvlan",
                properties: {
                    primary: false,
                    subnet: {
                        id: $subnet_id
                    },
                    privateIPAddressVersion: "IPv4",
                    privateIPAddressPrefixLength: "28"
                }
            }')
        
        # Merge new IP config with existing ones
        updated_ipconfigs=$(echo "$transformed_ipconfigs" | jq --argjson new "$new_ipconfig" '. + [$new]')
    fi

    # Extension profile
    extension_profile=$(echo "$vmss_json" | jq '.virtualMachineProfile.extensionProfile')
    # Remove existing CustomScript extension and transform others
    transformed_extension_profile=$(echo "$extension_profile" | jq '{
        extensions: [.extensions[] | select(.typePropertiesType != "CustomScript") | {
            name: .name,
            properties: ({
                autoUpgradeMinorVersion: .autoUpgradeMinorVersion,
                publisher: .publisher,
                type: .typePropertiesType,
                typeHandlerVersion: .typeHandlerVersion,
                settings: .settings
            } + (if .enableAutomaticUpgrade != null then {enableAutomaticUpgrade: .enableAutomaticUpgrade} else {} end)
              + (if .suppressFailures != null then {suppressFailures: .suppressFailures} else {} end)
              + (if .protectedSettings != null then {protectedSettings: .protectedSettings} else {} end))
        }]
    }')
    # Add the new CustomScript extension (replaces the old one)
    updated_extension_profile=$(echo "$transformed_extension_profile" | jq '.extensions += [{
        name: "ipvlan-setup",
        properties: {
            autoUpgradeMinorVersion: false,
            publisher: "Microsoft.Azure.Extensions",
            type: "CustomScript",
            typeHandlerVersion: "2.1",
            settings: {
                fileUris: ["https://raw.githubusercontent.com/Azure/telescope/refs/heads/cni-prototype/modules/kustomize/cni/stretch/setup_ipvlan.sh"],
                commandToExecute: "bash setup_ipvlan.sh"
            }
        }
    }]')

    echo "Creating ARM template with $(echo "$updated_ipconfigs" | jq 'length') IP configuration(s)..."
    echo "Updated Extension Profile: $(echo "$updated_extension_profile" | jq '.extensions | length') extensions"
    
    # Create clean ARM template with only the network profile update
    jq -n \
        --arg vmss_name "$vmss_name" \
        --arg location "$vmss_location" \
        --arg nic_name "$nic_name" \
        --argjson nic_primary "$nic_primary" \
        --argjson nic_accel "$nic_accel" \
        --argjson nic_ipfwd "$nic_ipfwd" \
        --argjson ipconfigs "$updated_ipconfigs" \
        --argjson updated_extension_profile "$updated_extension_profile" \
        '{
            "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentTemplate.json#",
            "contentVersion": "1.0.0.0",
            "resources": [
                {
                    "type": "Microsoft.Compute/virtualMachineScaleSets",
                    "apiVersion": "2025-04-01",
                    "name": $vmss_name,
                    "location": $location,
                    "properties": {
                        "virtualMachineProfile": {
                            "networkProfile": {
                                "networkInterfaceConfigurations": [
                                    {
                                        "name": $nic_name,
                                        "properties": {
                                            "primary": $nic_primary,
                                            "enableAcceleratedNetworking": $nic_accel,
                                            "enableIPForwarding": $nic_ipfwd,
                                            "ipConfigurations": $ipconfigs
                                        }
                                    }
                                ]
                            },
                            "extensionProfile": $updated_extension_profile
                        }
                    }
                }
            ]
        }' > vmss-secondary-ip-template-generated.json

    echo "Deploying ARM template with updated IP configuration..."
    
    # Deploy the generated ARM template
    az deployment group create \
        --resource-group $node_rg \
        --name "update-vmss-secondary-ip-$(date +%s)" \
        --template-file vmss-secondary-ip-template-generated.json \
        --mode Incremental
    
    deployment_status=$?
    
    if [ $deployment_status -eq 0 ]; then
        echo "Successfully updated VMSS with secondary IP configuration"
        
        # Update existing instances to apply the new configuration
        echo "Updating VMSS instances..."
        az vmss update-instances \
            --resource-group $node_rg \
            --name $vmss_name \
            --instance-ids "*"
        
        echo "VMSS update complete. Secondary IP configuration 'ipvlan' added with prefix length 28."
    else
        echo "Failed to update VMSS"
        cat vmss-secondary-ip-template-generated.json
        return 1
    fi
    
    # Clean up temporary files
    rm -f vmss-secondary-ip-template-generated.json
}

create_vm() {
    NODE_NAME="freenode"
    NODE_USER="azureuser"
    NODE_VM_SIZE="Standard_D8ds_v6"
    az vm create \
        --resource-group $RG \
        --name $NODE_NAME \
        --image Ubuntu2404 \
        --admin-username $NODE_USER \
        --generate-ssh-keys \
        --assign-identity \
        --public-ip-sku Standard \
        --vnet-name $VNET_NAME \
        --subnet $SUBNET \
        --size $NODE_VM_SIZE \
        --nsg-rule SSH
}

update_aks_vmss
# create_vm