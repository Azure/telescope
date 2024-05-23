#!/bin/bash

# DESC: Funtion for redeploying a VM in Azure
# ARGS: $1 (required): The name of the VM
#       $2 (required): The resource group of the VM
#       $3 (required): The path to the error file
# OUTS: Execution time of the redeployment
# NOTE: None 
redeploy_vm() {
    local vm_name=$1
    local resource_group=$2
    local error_file=$3
    local -i timeout=600
    local -i interval_seconds=3

    start_time=$(date +%s)

    # First time we redeploy th command waits for the VM to be in a running state
    # Subsequent redeployments do not wait for the VM to be in a running state
    # We use --no-wait to have consistent runs

    (
        az vm redeploy --resource-group "$resource_group" --name "$vm_name" --no-wait

        # The VM state does not change to stopped/stopping in the subsequent redeployments.
        # Sometimes it just dissapears from the instance view statuses.
        # On status is ProvisioningState/succeeded and the other show the state of the VM.

        az vm wait -g $resource_group --name $vm_name \
            --custom "length(instanceView.statuses) == \`1\` || \
     (length(instanceView.statuses) == \`2\` && instanceView.statuses[1].code != 'PowerState/running')" --interval $interval_seconds --timeout $timeout

        az vm wait -g $resource_group --name $vm_name \
            --custom "instanceView.statuses[?code=='PowerState/running']" --interval $interval_seconds --timeout $timeout
    ) 2>$error_file

    end_time=$(date +%s)

    echo "$(($end_time - $start_time))"
}