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
#   - $6: [optional] The security type to use (e.g. Standard, default value is TrustedLaunch)
#   - $7: [optional] The storage type to use (e.g. Premium_LRS, default value is Standard_LRS)
#   - $8: [optional] The tags to use (e.g. "'owner=azure_devops' 'creation_time=2024-03-11T19:12:01Z'", default value is empty)
#   - $9: [optional] The admin username to use (e.g. my_username, default value is azureuser)
#   - $10: [optional] The admin password to use (e.g. my_password, default value is Azur3User!FTW)
#
# Notes:
#   - the VM name is returned if no errors occurred
#
# Usage: create_vm <vm_name> <vm_size> <vm_os> <region> <resource_group> [security_type] [storage_type] [tags] [admin_username] [admin_password]
create_vm() {
    local vm_name=$1
    local vm_size=$2
    local vm_os=$3
    local region=$4
    local resource_group=$5
    local security_type="${6:-"TrustedLaunch"}"
    local storage_type="${7:-"Standard_LRS"}"
    local tags="${8:-"''"}"
    local admin_username="${9:-"azureuser"}"
    local admin_password="${10:-"Azur3User!FTW"}"

    if az vm create --resource-group "$resource_group" --name "$vm_name" --size "$vm_size" --image "$vm_os" --location "$region" --admin-username "$admin_username" --admin-password "$admin_password" --security-type "$security_type" --storage-sku "$storage_type" --output none --tags $tags; then
        echo "$vm_name"
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

    if az vm delete --resource-group "$resource_group" --name "$vm_name" --yes --output none; then
        echo "$vm_name"
    fi
}
