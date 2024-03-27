#!/bin/bash

# Description:
#   This function is used to create a VM in Azure.
#
# Parameters:
#   - $1: The name of the VM (e.g. my-vm)
#   - $2: The size of the VM (e.g. Standard_D2ds_v5)
#   - $3: The full URN of the OS image the VM will use (e.g. canonical:0001-com-ubuntu-server-focal:20_04-lts-gen2:latest)
#   - $4: The region where the VM will be created (e.g. us-east-1)
#   - $5: The resource group to use (e.g. rg-my-vm)
#   - $6: The NIC(s) to use (e.g. my-nic)
#   - $7: [optional] The security type to use (e.g. Standard, default value is TrustedLaunch)
#   - $8: [optional] The storage type to use (e.g. Premium_LRS, default value is Standard_LRS)
#   - $9: [optional] The tags to use (e.g. "'owner=azure_devops' 'creation_time=2024-03-11T19:12:01Z'", default value is empty)
#   - $10: [optional] The admin username to use (e.g. my_username, default value is azureuser)
#   - $11: [optional] The admin password to use (e.g. my_password, default value is Azur3User!FTW)
#
# Notes:
#   - the VM name is returned if no errors occurred
#
# Usage: create_vm <vm_name> <vm_size> <vm_os> <region> <resource_group> <nics> [security_type] [storage_type] [tags] [admin_username] [admin_password]
create_vm() {
    local vm_name=$1
    local vm_size=$2
    local vm_os=$3
    local region=$4
    local resource_group=$5
    local nics=$6
    local security_type="${7:-"TrustedLaunch"}"
    local storage_type="${8:-"Standard_LRS"}"
    local tags="${9:-"''"}"
    local admin_username="${10:-"azureuser"}"
    local admin_password="${11:-"Azur3User!FTW"}"

    if [[ -n "$nic" ]]; then
        if az vm create --resource-group "$resource_group" --name "$vm_name" --size "$vm_size" --image "$vm_os" --nics "$nics" --location "$region" --admin-username "$admin_username" --admin-password "$admin_password" --security-type "$security_type" --storage-sku "$storage_type" --nic-delete-option delete --os-disk-delete-option delete --output none --tags $tags; then
            echo "$vm_name"
        fi
    else
        if az vm create --resource-group "$resource_group" --name "$vm_name" --size "$vm_size" --image "$vm_os" --location "$region" --admin-username "$admin_username" --admin-password "$admin_password" --security-type "$security_type" --storage-sku "$storage_type" --nic-delete-option delete --os-disk-delete-option delete --output none --tags $tags; then
            echo "$vm_name"
        fi
    fi
}

# Description:
#   This function is used to delete a VM in Azure.
#
# Parameters:
#   - $1: The name of the VM (e.g. my-vm)
#   - $2: The resource group under which the VM was created (e.g. rg-my-vm)
#
# Notes:
#   - the VM name is returned if no errors occurred
#
# Usage: delete_vm <vm_name> <resource_group>
delete_vm() {
    local vm_name=$1
    local resource_group=$2

    if az vm delete --resource-group "$resource_group" --name "$vm_name" --force-deletion true --yes --output none; then
        echo "$vm_name"
    fi
}

# Description:
#   This function is used to create a NIC in Azure.
#
# Parameters:
#   - $1: The name of the NIC (e.g. nic_my-vm)
#   - $2: The resource group under which the VM was created (e.g. rg-my-vm)
#   - $3: [optional] The name of the VNet to use (e.g. my-vnet, default value is vnet_<nic_name>)
#   - $4: [optional] The name of the subnet to use (e.g. my-subnet, default value is subnet_<nic_name>)
#   - $5: [optional] Whether to use accelerated networking (e.g. true, default value is true)
#   - $6: [optional] The tags to use (e.g. "'owner=azure_devops' 'creation_time=2024-03-11T19:12:01Z'", default value is empty)
#
# Notes:
#   - the NIC name is returned if no errors occurred
#
# Usage: create_nic <nic_name> <resource_group> [vnet] [subnet] [accelerated_networking] [tags]
create_nic() {
    local nic_name=$1
    local resource_group=$2
    local vnet="${3:-"vnet_$nic_name"}"
    local subnet="${4:-"subnet_$nic_name"}"
    local accelerated_networking="${5:-"true"}"
    local tags="${6:-"''"}"

    if az network nic create --resource-group "$resource_group" --name "$nic_name" --vnet-name "$vnet" --subnet "$subnet" --accelerated-networking "$accelerated_networking" --tags $tags --output none; then
        echo "$nic_name"
    fi
}

# Description:
#   This function is used to delete a NIC in Azure.
#
# Parameters:
#   - $1: The name of the NIC (e.g. nic_my-vm)
#   - $2: The resource group under which the VM was created (e.g. rg-my-vm)
#
# Notes:
#   - the NIC name is returned if no errors occurred
#
# Usage: delete_nic <nic_name> <resource_group>
delete_nic() {
    local nic_name=$1
    local resource_group=$2

    if az network nic delete --resource-group "$resource_group" --name "$nic_name" --output none; then
        echo "$nic_name"
    fi
}
