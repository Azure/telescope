#!/bin/bash

# Description:
#   This function gets the names of disk instances by resource group(run id).
#
# Parameters:
#  - $1: run_id: the ID of the test run (e.g. c23f34-vf34g34g-3f34gf3gf4-fd43rf3f43)
# 
# Returns: name of the VM instance
# Usage: get_vm_instances_by_run_id <run_id>
get_vm_instances_name_by_run_id() {
    local resource_group=$1

    echo $(az resource list --resource-type Microsoft.Compute/virtualMachines --query "[?(tags.run_id == '"$resource_group"')].name" --output tsv)
}

# Description:
#   This function gets the VM info by name and resource group.
#
# Parameters:
#   - $1: The name of the VM (e.g. my-vm)
#   - $2: The resource group under which the VM was created (e.g. rg-my-vm)
#
# Returns: VM info
# Usage: get_vm_info <vm_name> <resource_group>
get_vm_info() {
    local vm_name=$1
    local resource_group=$2

    az vm show --name "$vm_name" --resource-group "$resource_group" --output json
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
#   - $7: The PIP to ping to check if the VM is running (e.g. 8.8.8.8)
#   - $8: The port to ping on the PIP (e.g. 22)
#   - $9: [optional] The security type to use (e.g. Standard, default value is TrustedLaunch)
#   - $10: [optional] The storage type to use (e.g. Premium_LRS, default value is Standard_LRS)
#   - $11: [optional] The timeout to use (e.g. 300, default value is 300)
#   - $12: [optional] The tags to use (e.g. "'owner=azure_devops' 'creation_time=2024-03-11T19:12:01Z'", default value is empty)
#   - $13: [optional] The admin username to use (e.g. my_username, default value is azureuser)
#   - $14: [optional] The admin password to use (e.g. my_password, default value is Azur3User!FTW)
#
# Usage: create_vm <vm_name> <vm_size> <vm_os> <region> <resource_group> <nics> <pip> [port] [security_type] [storage_type] [timeout] [tags] [admin_username] [admin_password]
create_vm() {
    local vm_name=$1
    local vm_size=$2
    local vm_os=$3
    local region=$4
    local resource_group=$5
    local nics=$6
    local pip=$7
    local port="${8:-"22"}"
    local security_type="${9:-"TrustedLaunch"}"
    local storage_type="${10:-"Standard_LRS"}"
    local timeout="${11:-"300"}"
    local tags="${12:-"''"}"
    local admin_username="${13:-"azureuser"}"
    local admin_password="${14:-"Azur3User!FTW"}"

    local ssh_file="/tmp/ssh-$vm_name-$(date +%s)"
    local cli_file="/tmp/cli-$vm_name-$(date +%s)"
    local error_file="/tmp/$vm_name-create_vm-error.txt"
    local output_file="/tmp/$vm_name-create_vm-output.txt"

    local start_time=$(date +%s)

    if [[ -n "$nics" ]]; then
        az vm create  --resource-group "$resource_group" --name "$vm_name" --size "$vm_size" --image "$vm_os" --nics "$nics" --location "$region" --admin-username "$admin_username" --admin-password "$admin_password" --security-type "$security_type" --storage-sku "$storage_type" --nic-delete-option delete --os-disk-delete-option delete --no-wait --output json --tags $tags 2>"$error_file" > "$output_file"
    else
        az vm create  --resource-group "$resource_group" --name "$vm_name" --size "$vm_size" --image "$vm_os" --location "$region" --admin-username "$admin_username" --admin-password "$admin_password" --security-type "$security_type" --storage-sku "$storage_type" --nic-delete-option delete --os-disk-delete-option delete --output json --no-wait --tags $tags 2>"$error_file" > "$output_file"
    fi

    local exit_code=$?

    if [[ $exit_code -eq 0 ]]; then
        (get_connection_timestamp "$pip" "$port" "$timeout" > "$ssh_file" ) &
        (get_running_state_timestamp "$vm_name" "$resource_group" "$timeout" > "$cli_file" ) &
        wait
    fi

    echo "$(create_vm_output "$vm_name" "$start_time" "$ssh_file" "$cli_file" "$error_file" "$exit_code")"
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

    az vm delete --resource-group "$resource_group" --name "$vm_name" --force-deletion true --yes --output json 2> "/tmp/$vm_name-delete_vm-error.txt" > "/tmp/$vm_name-delete_vm-output.txt"

    exit_code=$?

    (
        set -Ee
        function _catch {
            echo $(jq -c -n \
                --arg vm_name "$vm_name" \
            '{succeeded: "false", vm_name: $vm_name, vm_data: {error: "Unknown error"}}') | sed -E 's/\\n|\\r|\\t|\\s| /\|/g'
        }
        trap _catch ERR

        vm_data=$(cat "/tmp/$vm_name-delete_vm-output.txt")
        error=$(cat "/tmp/$vm_name-delete_vm-error.txt")

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
#   This function is used to create a PIP in Azure.
#
# Parameters:
#   - $1: The resource group under which the VM was created (e.g. rg-my-vm)
#   - $2: The name of the PIP (e.g. pip_my-vm)
#   - $3: The region where the PIP will be created (e.g. eastus)
#   - $4: [optional] The tags to use (e.g. "'owner=azure_devops' 'creation_time=2024-03-11T19:12:01Z'", default value is empty)
#
# Notes:
#   - the Public IP is returned if no errors occurred
#
# Usage: create_pip <resource_group> <pip_name> <region> [tags]
create_pip() {
    local resource_group=$1
    local pip_name=$2
    local region=$3
    local tags="${4:-"''"}"

    pip=$(az network public-ip create --resource-group "$resource_group" --name "$pip_name" --sku "Standard" --location "$region" --zone 1 2 3 --tags $tags --output json)
    echo "$pip" | jq -r ".publicIp.ipAddress"
}

# Description:
#   This function is used to create a NIC in Azure.
#
# Parameters:
#   - $1: The name of the NIC (e.g. nic_my-vm)
#   - $2: The resource group under which the VM was created (e.g. rg-my-vm)
#   - $3: The PIP name used for the NIC creation (e.g. pip_my-vm)
#   - $4: The NSG name used for the NIC creation (e.g. nsg_my-vm)
#   - $5: [optional] The name of the VNet to use (e.g. my-vnet, default value is vnet_<nic_name>)
#   - $6: [optional] The name of the subnet to use (e.g. my-subnet, default value is subnet_<nic_name>)
#   - $7: [optional] Whether to use accelerated networking (e.g. true, default value is true)
#   - $8: [optional] The tags to use (e.g. "'owner=azure_devops' 'creation_time=2024-03-11T19:12:01Z'", default value is empty)
#
# Notes:
#   - the NIC name is returned if no errors occurred
#
# Usage: create_nic <nic_name> <resource_group> <pip_name> <nsg_name> [vnet] [subnet] [accelerated_networking] [tags]
create_nic() {
    local nic_name=$1
    local resource_group=$2
    local pip_name=$3
    local nsg_name=$4
    local vnet="${5:-"vnet_$nic_name"}"
    local subnet="${6:-"subnet_$nic_name"}"
    local accelerated_networking="${7:-"true"}"
    local tags="${8:-"''"}"

    if az network nic create --resource-group "$resource_group" --name "$nic_name" --vnet-name "$vnet" --subnet "$subnet" --accelerated-networking "$accelerated_networking" --public-ip-address "$pip_name" --network-security-group "$nsg_name" --tags $tags --output none; then
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
#   This function is used to delete a PIP in Azure.
#
# Parameters:
#   - $1: The name of the PIP (e.g. pip_my-vm)
#   - $2: The name of the NIC (e.g. nic_my-vm)
#   - $3: The resource group under which the VM was created (e.g. rg-my-vm)
#
# Notes:
#   - the PIP name is returned if no errors occurred
#
# Usage: delete_pip <pip_name> <resource_group>
delete_pip() {
    local pip_name=$1
    local nic_name=$2
    local resource_group=$3

    try_dealloc=$(az network nic ip-config update --resource-group "$resource_group" --nic-name "$nic_name" --name "ipconfig1" --public-ip-address null --output none)

    if az network public-ip delete --resource-group "$resource_group" --name "$pip_name" --output none; then
        echo "$pip_name"
    fi
}

# Description:
#   This function is used to install CSE extension on a VM
#
# Parameters:
#   - $1: The name of the VM (e.g. my-vm)
#   - $2: The resource group under which the VM was created (e.g. rg-my-vm)
#   - $3: Commands to execute (e.g. '{"commandToExecute": "echo Hello World"}')
#
# Notes:
#   - an object with keys 'succeeded' and 'data' is returned, representing if the installation was successful or not and the command response
#
# Usage: install_vm_extension <vm_name> <resource_group>
install_vm_extension() {
    local vm_name=$1
    local resource_group=$2
    local command=${3:-'{"commandToExecute": "echo Hello World"}'}

    az vm extension set \
        --resource-group "$resource_group" \
        --vm-name "$vm_name" \
        --name "CustomScript" \
        --publisher "Microsoft.Azure.Extensions" \
        --settings "$command" 2> /tmp/$resource_group-$vm_name-install-extension-error.txt > /tmp/$resource_group-$vm_name-install-extension-output.txt

    exit_code=$?

    (
        extension_data=$(cat /tmp/$resource_group-$vm_name-install-extension-output.txt)
        error=$(cat /tmp/$resource_group-$vm_name-install-extension-error.txt)

        if [[ $exit_code -eq 0 ]]; then
            echo $(jq -c -n \
                --argjson extension_data "$extension_data" \
            '{succeeded: "true", data: $extension_data}')
        else
            echo $(jq -c -n \
                --arg error "$error" \
            '{succeeded: "false", data: {error: $error}}')
        fi
    )
}

# Description:
#   This function checks the status of a VM in Azure.
#
# Parameters:
#   - $1: The name of the VM (e.g. my-vm)
#   - $2: The resource group under which the VM was created (e.g. rg-my-vm)
#   - $3: The timeout value in seconds (e.g. 300)
#
# Returns: true if the VM has the expected status within the timeout, false otherwise
# Usage: get_running_state_timestamp <vm_name> <resource_group> <timeout>
get_running_state_timestamp() {
    local vm_name=$1
    local resource_group=$2
    local timeout=$3

    local error_file="/tmp/azure-cli-"$(date +%s)"-error.txt"
    az vm wait --timeout $timeout -g "$resource_group" -n "$vm_name" --interval 15 --created 2> $error_file
    local exit_code=$?


    if [[ $exit_code -eq 0 ]]; then
        echo $(jq -c -n \
            --arg timestamp "$(date +%s)" \
        '{success: "true", timestamp: $timestamp}')
    else
        echo $(jq -c -n \
            --arg error "$(cat $error_file)" \
        '{sucess: "false", error: $error}')
    fi
}

# Description:
#   This method processes the results of SSH and CLI commands and returns the appropriate response.

# Parameters:
#   - $1: The name of the VM (e.g. my-vm)
#   - $2: The start time of the command execution
#   - $3: The SSH file path
#   - $4: The CLI file path
#   - $5: The error file path
#   - $6: The create command exit code
#
# Returns: The response JSON string
# Usage: process_result <vm_name> <start_time> <ssh_file> <cli_file> <error_file> <command_exit_code>
create_vm_output() {
    local vm_name="$1"
    local start_time="$2"
    local ssh_file="$3"
    local cli_file="$4"
    local error_file="$5"
    local command_exit_code="$6"

    set -Ee
    function _catch {
        echo $(jq -c -n \
            --arg vm_name "$instance_name" \
        '{succeeded: "false", vm_name: $vm_name, vm_data: {error: "Unknown error"}}') | sed -E 's/\\n|\\r|\\t|\\s| /\|/g'
    }
    trap _catch ERR

    local error=$(cat "$error_file")

    if [[ -n "$error" && $command_exit_code -ne 0 ]]; then
        if [[ "${error:0:8}" == "ERROR: {" ]]; then
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
    elif [[ "$command_exit_code" -ne 0 ]]; then
        echo $(jq -c -n \
            --arg vm_name "$vm_name" \
            --arg command_exit_code "$command_exit_code" \
        '{succeeded: "false", vm_name: $vm_name, vm_data: {error: "Command exited with code $command_exit_code. No error available."}}') | sed -E 's/\\n|\\r|\\t|\\s| /\|/g'
    else
        echo "$(process_results "$ssh_file" "$cli_file" "$error_file" "$start_time" "$vm_name" )"
    fi
}
