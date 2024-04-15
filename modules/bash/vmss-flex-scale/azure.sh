#!/bin/bash

# Description:
#   This function is used to create a VMSS in Azure.
#
# Parameters:
#   - $1: The name of the VMSS (e.g. my-vmss)
#   - $2: The size of the VM (e.g. Standard_D2ds_v5)
#   - $3: The full URN of the OS image the VM will use (e.g. canonical:0001-com-ubuntu-server-focal:20_04-lts-gen2:latest)
#   - $4: The region where the VM will be created (e.g. us-east-1)
#   - $5: The resource group to use (e.g. rg-my-vm)
#   - $6: The NIC(s) to use (e.g. my-nic)
#   - $7: [optional] The security type to use (e.g. Standard, default value is TrustedLaunch)
#   - $8: [optional] The storage type to use (e.g. Premium_LRS, default value is Standard_LRS)
#   - $9: [optional] The tags to use (e.g. "'owner=azure_devops' 'creation_time=2024-03-11T19:12:01Z'", default value is empty)
#
# Usage: create_vm <vm_name> <vm_size> <vm_os> <region> <resource_group> <nics> [security_type] [storage_type] [tags] [admin_username] [admin_password]
create_vmss() {
	local vmss_name=$1
    local vm_size=$2
    local vm_os=$3
    local region=$4
    local resource_group=$5
    local network_security_group=$6
    local vnet_name=$7
    local subnet=$8
    local security_type="${9:-"TrustedLaunch"}"
    local tags="${10:-"''"}"
    local admin_username="${11:-"azureuser"}"
    local admin_password="${12:-"Azur3User!FTW"}"

	az vmss create --name "$vmss_name" --resource-group "$resource_group" --image "$vm_os" --vm-sku "$vm_size" --instance-count 1 --location "$region" --nsg "$network_security_group" --vnet-name "$vnet_name" --subnet "$subnet" --security-type "$security_type" --tags $tags --admin-username "$admin_username" --admin-password "$admin_password" -o json 2> /tmp/$resource_group-$vmss_name-create_vmss-error.txt > /tmp/$resource_group-$vmss_name-create_vmss-output.txt

    exit_code=$?

    (
        set -Ee
        function _catch {
            echo $(jq -c -n \
                --arg vmss_name "$vmss_name" \
            '{succeeded: "false", vmss_name: $vmss_name, vmss_data: {error: "Unknown error"}}') | sed -E 's/\\n|\\r|\\t|\\s| /\|/g'
        }
        trap _catch ERR

        vmss_data=$(cat /tmp/$resource_group-$vmss_name-create_vmss-output.txt)
        error=$(cat /tmp/$resource_group-$vmss_name-create_vmss-error.txt)

        if [[ $exit_code -eq 0 ]]; then
            echo $(jq -c -n \
                --arg vmss_name "$vmss_name" \
                --argjson vmss_data "$vmss_data" \
            '{succeeded: "true", vmss_name: $vmss_name, vmss_data: $vmss_data}') | sed -E 's/\\n|\\r|\\t|\\s| /\|/g'
        else
            if [[ -n "$error" ]] && [[ "${error:0:8}" == "ERROR: {" ]]; then
                echo $(jq -c -n \
                    --arg vmss_name "$vmss_name" \
                    --argjson vmss_data "${error:7}" \
                '{succeeded: "false", vmss_name: $vmss_name, vmss_data: {error: $vmss_data}}')` | sed -E 's/\\n|\\r|\\t|\\s| /\|/g'`
            else
                echo $(jq -c -n \
                    --arg vmss_name "$vmss_name" \
                    --arg vmss_data "$error" \
                '{succeeded: "false", vmss_name: $vmss_name, vmss_data: {error: $vmss_data}}') | sed -E 's/\\n|\\r|\\t|\\s| /\|/g'
            fi
        fi
    )

}

# Test only
scale_vmss() {
    local vmss_name=$1
    local resource_group=$2
    local vmss_capacity=$3
    
    az vmss scale --name "$vmss_name" --new-capacity "$vmss_capacity" --resource-group "$resource_group" -o json 2> /tmp/$resource_group-$vmss_name-scale_vmss-error.txt > /tmp/$resource_group-$vmss_name-scale_vmss-output.txt
}

delete_vmss() {
    local vmss_name=$1
    local resource_group=$2

    az vmss delete --name "$vmss_name" --resource-group "$resource_group" -o json 2> /tmp/$resource_group-$vmss_name-delete_vmss-error.txt > /tmp/$resource_group-$vmss_name-delete_vmss-output.txt

    exit_code=$?

    (
        set -Ee
        function _catch {
            echo $(jq -c -n \
                --arg vmss_name "$vmss_name" \
            '{succeeded: "false", vmss_name: $vmss_name, vmss_data: {error: "Unknown error"}}') | sed -E 's/\\n|\\r|\\t|\\s| /\|/g'
        }
        trap _catch ERR

        error=$(cat /tmp/$resource_group-$vmss_name-delete_vmss-error.txt)

        if [[ $exit_code -eq 0 ]]; then
            echo $(jq -c -n \
                --arg vmss_name "$vmss_name" \
            '{succeeded: "true", vmss_name: $vmss_name}') | sed -E 's/\\n|\\r|\\t|\\s| /\|/g'
        else
            if [[ -n "$error" ]] && [[ "${error:0:8}" == "ERROR: {" ]]; then
                echo $(jq -c -n \
                    --arg vmss_name "$vmss_name" \
                '{succeeded: "false", vmss_name: $vmss_name, vmss_data: {error: $vmss_data}}')` | sed -E 's/\\n|\\r|\\t|\\s| /\|/g'`
            else
                echo $(jq -c -n \
                    --arg vmss_name "$vmss_name" \
                    --arg vmss_data "$error" \
                '{succeeded: "false", vmss_name: $vmss_name, vmss_data: {error: $vmss_data}}') | sed -E 's/\\n|\\r|\\t|\\s| /\|/g'
            fi
        fi
    )

}