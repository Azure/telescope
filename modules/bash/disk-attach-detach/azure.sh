#!/bin/bash

#Description
#   This script contains the functions to manage the resources in the resource group.
#
# Parameters:
#  - $1:  run_id: the ID of the test run (e.g. c23f34-vf34g34g-3f34gf3gf4-fd43rf3f43)
# 
# Returns: name of the VM instance
# Usage: get_vm_instance_by_name <run_id>
get_vm_instance_by_name() {
    local run_id=$1

    echo  $(az resource list --resource-type Microsoft.Compute/virtualMachines --query "[?(tags.run_id == '$run_id')].name" --output tsv)
}

#Description
#   This function gets the disk instances by name.
#
# Parameters:
#  - $1:  run_id: the ID of the test run (e.g. c23f34-vf34g34g-3f34gf3gf4-fd43rf3f43)
#
# Returns: name of the disk instances
# Usage: get_disk_instances_by_name <run_id>
get_disk_instances_by_name() {
    local run_id=$1
    
    echo  "$(az resource list --resource-type Microsoft.Compute/disks --query "[?(tags.run_id == '${run_id}')].name"  --output tsv)"
}

#Description
#   This function ataches a disk to a vm.
#
# Parameters:
#  - $1:  vm_name: the name of the VM instance (e.g. vm-1)
#  - $2:  disk_name: the name of the disk instance (e.g. disk-1)
#  - $3:  resource_group: the name of the resource group (e.g. c23f34-vf34g34g-3f34gf3gf4-fd43rf3f43)
#
# Returns: Error message of the operation otherwise nothing
# Usage: attach_disk <vm_name> <disk_name> <resource_group>
attach_disk() {
    local vm_name=$1
    local disk_name=$2
    local resource_group=$3

    echo "$(az vm disk attach -g $resource_group --vm-name ${vm_name} --name ${disk_name} 2>&1)"
}

#Description
#   This function detaches a disk from a vm.
#
# Parameters:
#  - $1:  vm_name: the name of the VM instance (e.g. vm-1)
#  - $2:  disk_name: the name of the disk instance (e.g. disk-1)
#  - $3:  resource_group: the name of the resource group (e.g. c23f34-vf34g34g-3f34gf3gf4-fd43rf3f43)
#
# Returns: Error message of the operation otherwise nothing
# Usage: detach_disk <vm_name> <disk_name> <resource_group>
detach_disk() {
    local vm_name=$1
    local disk_name=$2
    local resource_group=$3

    echo "$(az vm disk detach -g $resource_group --vm-name ${vm_name} --name ${disk_name} 2>&1)"
}

#Description
#   This function validates the resources in the resource group.
#
# Parameters:
#  = $1:  run_id: the ID of the test run (e.g. c23f34-vf34g34g-3f34gf3gf4-fd43rf3f43)
#
# Returns: None
# Usage: validate_resources <run_id>
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

#Description
#   This function gets the storage type and size of a disk.
#
# Parameters:
#  - $1:  disk_name: the name of the disk instance (e.g. disk-1)
#
# Returns: JSON object containing the storage type and size of the disk
# Usage: get_disk_storage_type_and_size <disk_name>
get_disk_storage_type_and_size() {
    local disk_name=$1

    echo $(az disk list --query "[?name=='$disk_name'].{StorageType:sku.name, Size:diskSizeGB}" --output json)
}

#Description
#   This function gets the operating system and size of a VM.
#
# Parameters:
#  - $1:  vm_name: the name of the VM instance (e.g. vm-1)
#  - $2:  resource_group: the name of the resource group (e.g. c23f34-vf34g34g-3f34gf3gf4-fd43rf3f43)
#
# Returns: JSON object containing the operating system and size of the VM
# Usage: get_vm_properties <vm_name> <resource_group>
get_vm_properties() {
    local vm_name=$1
    local resource_group=$2

    echo "$(az vm show --name $vm_name --resource-group $resource_group --query "{OperatingSystem: storageProfile.osDisk.osType, Size: hardwareProfile.vmSize}" --output json)"
}

#Description
#   This function gets the region of a resource group.
#
# Parameters:
#  - $1:  resource_group: the name of the resource group (e.g. c23f34-vf34g34g-3f34gf3gf4-fd43rf3f43)
#
# Returns: The region of the resource group
# Usage: get_region <resource_group>
get_region() {
    local resource_group=$1
        
    echo $(az group show --name $resource_group --query "location" --output tsv)
}
