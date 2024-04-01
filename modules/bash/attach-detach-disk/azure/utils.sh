#function to get the vm instance from the environment by name
get_vm_instance_by_name() {
    local run_id=$1

    echo  $(az resource list --resource-type Microsoft.Compute/virtualMachines --query "[?(tags.run_id == '$run_id')].name" --output tsv)
}

#function to get the disk instance from the environment by name
get_disk_instance_by_name() {
    local run_id=$1
    local scenario_type=$2
    local scenario_name=$3
    
    echo  $(az resource list --resource-type Microsoft.Compute/disks --query "[?(tags.run_id == '${run_id}')].name" --output tsv)
}

#function to attach disk to VM
attach_disk() {
    local vm_name=$1
    local disk_name=$2
    local resource_group=$3

    result=$(az vm disk attach -g $resource_group --vm-name ${vm_name} --name ${disk_name} 2>&1)
    if [ $? -eq 0 ] && [[ $result != *"ERROR"* ]]; then
        echo "success"
    else
        echo "failed"
    fi
}

#function to detach disk to VM
detach_disk() {
    local vm_name=$1
    local disk_name=$2
    local resource_group=$3

    result=$(az vm disk detach -g $resource_group --vm-name ${vm_name} --name ${disk_name} 2>&1)
    if [ $? -eq 0 ] && [[ $result != *"ERROR"* ]]; then
        echo "success"
    else
        echo "failed"
    fi
}

#function to validate the resources in the resource group
validate_resources() {
    local run_id=$1
    
    # Retrieve VMs from the resource group
    vm_count=$(az vm list --resource-group $run_id --query "length([])")

    # Check if there is only one VM
    if [ $vm_count -ne 1 ]; then
        echo "Error: There should be exactly one VM in the resource group."
        exit 1
    fi

    # Retrieve disks from the resource group
    disk_count=$(az disk list --resource-group $run_id --query "length([])")

    # Check if there is at least one disk
    if [ $disk_count -lt 1 ]; then
        echo "Error: There should be at least one disk in the resource group."
        exit 1
    fi
}