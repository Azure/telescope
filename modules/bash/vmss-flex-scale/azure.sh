#!/bin/bash

# Description:
#   This function is used to create a VMSS in Azure.
#
# Parameters:
#   - $1: The name of the VMSS (e.g. vmss-1-1233213123)
#   - $2: The size of the VM used in the VMSS (e.g. c3-highcpu-4)
#   - $3: The OS identifier the VM will use (e.g. projects/ubuntu-os-cloud/global/images/ubuntu-2004-focal-v20240229)
#   - $4: The number of VM instances in the VMSS (e.g. 1)
#   - $5: The region where the VMSS will be created (e.g. us-east1)
#   - $6: The run id
#   - $7: The network security group (eg. my-nsg)
#   - $8: The virtual network name (e.g. my-vnet)
#   - $9: The subnet (e.g. my-subnet)
#   - $10: [optional] The security type (e.g. TrustedLaunch)
#   - $11: [optional] The tags to use (e.g. "owner=azure_devops,creation_time=2024-03-11T19:12:01Z")
#   - $12: [optional] The admin username to use (e.g. my_username, default value is azureuser)
#   - $13: [optional] The admin password to use (e.g. my_password, default value is Azur3User!FTW)
#
# Usage: create_vmss <vmss_name> <vm_size> <vm_os> <vm_instances> <region> <resource_group> <network_security_group> <vnet_name> <subnet> [security_type] [tags] [admin_username] [admin_password]
create_vmss() {
    local vmss_name=$1
    local vm_size=$2
    local vm_os=$3
    local vm_instances=$4
    local region=$5
    local resource_group=$6
    local network_security_group=$7
    local vnet_name=$8
    local subnet=$9
    local security_type="${10:-"TrustedLaunch"}"
    local tags="${11:-"''"}"
    local admin_username="${12:-"azureuser"}"
    local admin_password="${13:-"Azur3User!FTW"}"

    az vmss create --name "$vmss_name" --resource-group "$resource_group" --image "$vm_os" --vm-sku "$vm_size" --instance-count $vm_instances --location "$region" --nsg "$network_security_group" --vnet-name "$vnet_name" --subnet "$subnet" --security-type "$security_type" --tags $tags --admin-username "$admin_username" --admin-password "$admin_password" -o json 2> /tmp/$resource_group-$vmss_name-create_vmss-error.txt > /tmp/$resource_group-$vmss_name-create_vmss-output.txt

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

# This method will be used in the future when scaling is required for Azure.
# Description:
#   This function is used to scale (in/out) a VMSS in Azure.
#
# Parameters:
#   - $1: The name of the VMSS (e.g. my-vmss)
#   - $2: The resource group under which the VMSS was created (e.g. rg-my-vmss)
#   - $3: The new VM capacity for the VMSS (e.g. 20)
#
# Usage: scale_vmss <vmss_name> <resource_group> <vmss_capacity>
scale_vmss() {
    local vmss_name=$1
    local resource_group=$2
    local vmss_capacity=$3
    
    az vmss scale --name "$vmss_name" --new-capacity $vmss_capacity --resource-group "$resource_group" -o json 2> /tmp/$resource_group-$vmss_name-scale_vmss-error.txt > /tmp/$resource_group-$vmss_name-scale_vmss-output.txt
}

# Description:
#   This function is used to delete a VMSS in Azure.
#
# Parameters:
#   - $1: The name of the VMSS (e.g. my-vmss)
#   - $2: The resource group under which the VMSS was created (e.g. rg-my-vmss)
#
# Usage: delete_vm <vmss_name> <resource_group>
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