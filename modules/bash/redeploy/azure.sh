#!/bin/bash

# DESC: Get the name of the virtual machine instances by run id
# ARGS: $1 (required): The run id
# OUTS: The name of the virtual machine instances
# NOTE: The run id is usually the resource group name
azure::get_vm_instances_name_by_run_id() {
    local resource_group=$1

    az resource list \
        --resource-type Microsoft.Compute/virtualMachines \
        --query "[?(tags.run_id == '"$resource_group"')].name" \
        --output tsv
}

# DESC: Get the instance view for a vm
# ARGS: $1 (required): The resource group of the VM
#       $2 (required): The name of the VM
# OUTS: The json of the instance view
# NOTE: None
azure::get_vm_instance_view_json() {
    local resource_group=$1
    local vm_name=$2

    az vm get-instance-view --resource-group $1 --name $2
}

# DESC: Get the IP address of a VM
# ARGS: $1 (required): The resource group of the VM
#       $2 (required): The name of the VM
# OUTS: The IP address of the VM
# NOTE: None
azure::get_vm_ip_address() {
    local resource_group=$1
    local vm_name=$2

    az vm show -d -g $resource_group -n $vm_name --query publicIps -o tsv
}

# DESC: Function for redeploying a VM in Azure
# ARGS: $1 (required): The name of the VM
#       $2 (required): The resource group of the VM
#       $3 (required): The path to the error file
# OUTS: Execution time of the redeploy
# NOTE: None 
azure::redeploy_vm() {
    local vm_name=$1
    local resource_group=$2
    local error_file=$3
    local ssh_port=${4:-"22"}
    local timeout=${5:-"300"}
    local interval_seconds=${6:-"1"}
    local current_ip="$(azure::get_vm_ip_address $resource_group $vm_name)"

    start_time=$(date +%s)
    # First time we redeploy, the command waits for the VM to be in a running state
    # Subsequent redeploys do not wait for the VM to be in a running state
    # We use --no-wait to have consistent runs
    (
        az vm redeploy --resource-group "$resource_group" --name "$vm_name" --no-wait
        
        # The VM state does not change to stopped/stopping in the subsequent redeploys.
        # Sometimes it just disappears from the instance view statuses.
        # One status is ProvisioningState/succeeded and the other shows the state of the VM.
        az vm wait -g $resource_group --name $vm_name \
            --custom "length(instanceView.statuses) == \`1\` || \
            (length(instanceView.statuses) == \`2\` && instanceView.statuses[1].code != 'PowerState/running')" \
             --interval $interval_seconds --timeout $timeout

        az vm wait -g $resource_group --name $vm_name \
            --custom "instanceView.statuses[?code=='PowerState/running']" --interval $interval_seconds --timeout $timeout
        
        connection_successful=$(utils::test_connection $current_ip $ssh_port $timeout) 
        if [ "$connection_successful" == "false" ]; then
            echo "SSH TIMEOUT" 1>&2
        fi
    ) 1> /dev/null 2>>$error_file
    end_time=$(date +%s)

    echo "$(($end_time - $start_time))"
}