#!/bin/bash

# Description:
#   This script contains the functions to manage the resources in the resource group.
#
# Parameters:
#  - $1: run_id: the ID of the test run (e.g. c23f34-vf34g34g-3f34gf3gf4-fd43rf3f43)
# 
# Returns: name of the VM instance
# Usage: get_vm_instance_by_name <run_id>
get_vm_instance_by_name() {
    local run_id=$1

    echo $(az resource list --resource-type Microsoft.Compute/virtualMachines --query "[?(tags.run_id == '"$run_id"')].name" --output tsv)
}

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

    if [[ -n "$nics" ]]; then
        az vm create --resource-group "$resource_group" --name "$vm_name" --size "$vm_size" --image "$vm_os" --nics "$nics" --location "$region" --admin-username "$admin_username" --admin-password "$admin_password" --security-type "$security_type" --storage-sku "$storage_type" --nic-delete-option delete --os-disk-delete-option delete --output json --tags $tags 2> /tmp/$resource_group-$vm_name-create_vm-error.txt > /tmp/$resource_group-$vm_name-create_vm-output.txt
    else
        az vm create --resource-group "$resource_group" --name "$vm_name" --size "$vm_size" --image "$vm_os" --location "$region" --admin-username "$admin_username" --admin-password "$admin_password" --security-type "$security_type" --storage-sku "$storage_type" --nic-delete-option delete --os-disk-delete-option delete --output json --tags $tags 2> /tmp/$resource_group-$vm_name-create_vm-error.txt > /tmp/$resource_group-$vm_name-create_vm-output.txt
    fi

    exit_code=$?

    (
        set -Ee
        function _catch {
            echo $(jq -c -n \
                --arg vm_name "$vm_name" \
            '{succeeded: "false", vm_name: $vm_name, vm_data: {error: "Unknown error"}}') | sed -E 's/\\n|\\r|\\t|\\s| /\|/g'
        }
        trap _catch ERR

        vm_data=$(cat /tmp/$resource_group-$vm_name-create_vm-output.txt)
        error=$(cat /tmp/$resource_group-$vm_name-create_vm-error.txt)

        if [[ $exit_code -eq 0 ]]; then
            echo $(jq -c -n \
                --arg vm_name "$vm_name" \
                --argjson vm_data "$vm_data" \
            '{succeeded: "true", vm_name: $vm_name, vm_data: $vm_data}') | sed -E 's/\\n|\\r|\\t|\\s| /\|/g'
        else
            if [[ -n "$error" ]] && [[ "${error:0:8}" == "ERROR: {" ]]; then
                echo $(jq -c -n \
                    --arg vm_name "$vm_name" \
                    --argjson vm_data "${error:7}" \
                '{succeeded: "false", vm_name: $vm_name, vm_data: {error: $vm_data}}') | sed -E 's/\\n|\\r|\\t|\\s| /\|/g'
            else
                echo $(jq -c -n \
                    --arg vm_name "$vm_name" \
                    --arg vm_data "$error" \
                '{succeeded: "false", vm_name: $vm_name, vm_data: {error: $vm_data}}') | sed -E 's/\\n|\\r|\\t|\\s| /\|/g'
            fi
        fi
    )
}

# Description:
#   This function is used to delete a VM in Azure.
#
# Parameters:
#   - $1: The name of the VM (e.g. my-vm)
#   - $2: The resource group under which the VM was created (e.g. rg-my-vm)
#
# Usage: delete_vm <vm_name> <resource_group>
delete_vm() {
    local vm_name=$1
    local resource_group=$2

    az vm delete --resource-group "$resource_group" --name "$vm_name" --force-deletion true --yes --output json 2> /tmp/$resource_group-$vm_name-delete_vm-error.txt > /tmp/$resource_group-$vm_name-delete_vm-output.txt

    exit_code=$?

    (
        set -Ee
        function _catch {
            echo $(jq -c -n \
                --arg vm_name "$vm_name" \
            '{succeeded: "false", vm_name: $vm_name, vm_data: {error: "Unknown error"}}') | sed -E 's/\\n|\\r|\\t|\\s| /\|/g'
        }
        trap _catch ERR

        vm_data=$(cat /tmp/$resource_group-$vm_name-delete_vm-output.txt)
        error=$(cat /tmp/$resource_group-$vm_name-delete_vm-error.txt)

        if [[ $exit_code -eq 0 ]]; then
            echo $(jq -c -n \
                --arg vm_name "$vm_name" \
                --argjson vm_data "{}" \
            '{succeeded: "true", vm_name: $vm_name, vm_data: $vm_data}') | sed -E 's/\\n|\\r|\\t|\\s| /\|/g'
        else
            if [[ -n "$error" ]] && [[ "${error:0:8}" == "ERROR: {" ]]; then
                echo $(jq -c -n \
                    --arg vm_name "$vm_name" \
                    --argjson vm_data "${error:7}" \
                '{succeeded: "false", vm_name: $vm_name, vm_data: {error: $vm_data}}') | sed -E 's/\\n|\\r|\\t|\\s| /\|/g'
            else
                echo $(jq -c -n \
                    --arg vm_name "$vm_name" \
                    --arg vm_data "$error" \
                '{succeeded: "false", vm_name: $vm_name, vm_data: {error: $vm_data}}') | sed -E 's/\\n|\\r|\\t|\\s| /\|/g'
            fi
        fi
    )
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

# Description:
#   This function is used to install CSE extension on a VM
#
# Parameters:
#   - $1: The name of the VM (e.g. my-vm)
#   - $2: The resource group under which the VM was created (e.g. rg-my-vm)
#
# Notes:
#   - an object with keys 'succeeded' and 'data' is returned, representing if the installation was successful or not and the command response
#
# Usage: install_vm_extension <vm_name> <resource_group>
install_vm_extension() {
    local vm_name=$1
    local resource_group=$2

    az vm extension set \
        --resource-group "$resource_group" \
        --vm-name "$vm_name" \
        --name "CustomScript" \
        --publisher "Microsoft.Azure.Extensions" \
        --settings '{"commandToExecute": "echo Hello World"}' 2> /tmp/$resource_group-$vm_name-install-extension-error.txt > /tmp/$resource_group-$vm_name-install-extension-output.txt

    exit_code=$?

    (
        set -Ee
        function _catch {
            echo $(jq -c -n \
            '{succeeded: "false", data: {error: "Unknown error"}}') | sed -E 's/\\n|\\r|\\t|\\s| /\|/g'
        }
        trap _catch ERR

        extension_data=$(cat /tmp/$resource_group-$vm_name-install-extension-output.txt)
        error=$(cat /tmp/$resource_group-$vm_name-install-extension-error.txt)

        if [[ $exit_code -eq 0 ]]; then
            echo $(jq -c -n \
                --argjson extension_data "$extension_data" \
            '{succeeded: "true", data: $extension_data}') | sed -E 's/\\n|\\r|\\t|\\s| /\|/g'
        else
            echo $(jq -c -n \
                --arg error "$error" \
                '{succeeded: "false", data: {error: $error}}') | sed -E 's/\\n|\\r|\\t|\\s| /\|/g'
        fi
    )
}