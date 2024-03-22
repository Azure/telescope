#!/bin/bash

# Description:
#   This function is used to generate a VM name
#
# Parameters:
#   - $1: The index of the VM
#   - $2: The run id
#
# Notes:
#   - the VM name is truncated to 15 characters due to Windows limitations
#
# Usage: get_vm_name <index> <run_id>
get_vm_name() {
    local i=$1
    local run_id=$2

    local vm_name="vm-$i-$run_id"
    vm_name="${vm_name:0:15}"
    vm_name="${vm_name%-}"

    echo $vm_name
}

# Description:
#   This function is used to to measure the time it takes to create and delete a VM and save results in JSON format
#
# Parameters:
#   - $1: The cloud provider (e.g. azure, aws, gcp)
#   - $2: The name of the VM (e.g. vm-1-1233213123)
#   - $3: The size of the VM (e.g. c3-highcpu-4)
#   - $4: The OS identifier the VM will use (e.g. projects/ubuntu-os-cloud/global/images/ubuntu-2004-focal-v20240229)
#   - $5: The region where the VM will be created (e.g. us-east1)
#   - $6: The resource group (e.g. my-resource-group)
#   - $7: The security group (e.g. my-security-group)
#   - $8: The subnet (e.g. my-subnet)
#   - $9: [optional] The accelerator to use (e.g. count=8,type=nvidia-h100-80gb, default value is empty)
#   - $10: The security type (e.g. TrustedLaunch)
#   - $11: The storage type (e.g. Premium_LRS)
#   - $12: The result directory where to place the results in JSON format
#   - $13: The tags to use (e.g. "owner=azure_devops,creation_time=2024-03-11T19:12:01Z")
#
# Usage: measure_create_delete_vm <cloud> <vm_name> <vm_size> <vm_os> <region> <resource_group> <security_group> <subnet> <accelerator> <security_type> <storage_type> <result_dir> <tags>
measure_create_delete_vm() {
    local cloud=$1
    local vm_name=$2
    local vm_size=$3
    local vm_os=$4
    local region=$5
    local resource_group=$6
    local security_group=$7
    local subnet=$8
    local accelerator=$9
    local security_type=${10}
    local storage_type=${11}
    local result_dir=${12}
    local tags=${13}

    local test_details="{ \
        \"cloud\": \"$cloud\", \
        \"name\": \"$vm_name\", \
        \"size\": \"$vm_size\", \
        \"os\": \"$vm_os\", \
        \"region\": \"$region\", \
        \"accelerator\": \"$accelerator\", \
        \"security_type\": \"$security_type\", \
        \"storage_type\": \"$storage_type\""
    
    echo "Measuring $cloud VM creation/deletion for with the following details: 
- VM name: $vm_name
- VM size: $vm_size
- VM OS: $vm_os
- Region: $region
- Resource group: $resource_group
- Security group: $security_group
- Subnet: $subnet
- Accelerator: $accelerator
- Security type: $security_type
- Storage type: $storage_type
- Tags: $tags"
    
    instance_id=$(measure_create_vm "$cloud" "$vm_name" "$vm_size" "$vm_os" "$region" "$resource_group" "$security_group" "$subnet" "$accelerator" "$security_type" "$storage_type" "$result_dir" "$test_details" "$tags")

    if [ -n "$instance_id" ] && [[ "$instance_id" != Error* ]]; then
        instance_id=$(measure_delete_vm "$cloud" "$instance_id" "$region" "$resource_group" "$result_dir" "$test_details")
    fi
}

# Description:
#   This function is used to to measure the time it takes to create a VM and save results in JSON format
#
# Parameters:
#   - $1: The cloud provider (e.g. azure, aws, gcp)
#   - $2: The name of the VM (e.g. vm-1-1233213123)
#   - $3: The size of the VM (e.g. c3-highcpu-4)
#   - $4: The OS identifier the VM will use (e.g. projects/ubuntu-os-cloud/global/images/ubuntu-2004-focal-v20240229)
#   - $5: The region where the VM will be created (e.g. us-east1)
#   - $6: The resource group (e.g. my-resource-group)
#   - $7: The security group (e.g. my-security-group)
#   - $8: The subnet (e.g. my-subnet)
#   - $9: [optional] The accelerator to use (e.g. count=8,type=nvidia-h100-80gb, default value is empty)
#   - $10: The security type (e.g. TrustedLaunch)
#   - $11: The storage type (e.g. Premium_LRS)
#   - $12: The result directory where to place the results in JSON format
#   - $13: The test details in JSON format
#   - $14: The tags to use (e.g. "owner=azure_devops,creation_time=2024-03-11T19:12:01Z")
#
# Notes:
#   - the Instance ID is returned if no errors occurred
#
# Usage: measure_create_vm <cloud> <vm_name> <vm_size> <vm_os> <region> <resource_group> <security_group> <subnet> <accelerator> <security_type> <storage_type> <result_dir> <test_details>
measure_create_vm() {
    local cloud=$1
    local vm_name=$2
    local vm_size=$3
    local vm_os=$4
    local region=$5
    local resource_group=$6
    local security_group=$7
    local subnet=$8
    local accelerator=$9
    local security_type=${10}
    local storage_type=${11}
    local result_dir=${12}
    local test_details=${13}
    local tags=${14}

    {
        local start_time=$(date +%s)
        case $cloud in
            azure)
            instance_id=$(create_vm "$vm_name" "$vm_size" "$vm_os" "$region" "$resource_group" "$security_type" "$storage_type" "$tags")
            ;;
            aws)
            instance_id=$(create_ec2 "$vm_name" "$vm_size" "$vm_os" "$region" "$security_group" "$subnet" "$tags")
            ;;
            gcp)
            instance_id=$(create_vm "$vm_name" "$vm_size" "$vm_os" "$region" "$accelerator" "$tags")
            ;;
            *)
            exit 1 # cloud provider unknown
            ;;
        esac
        
        if [ -n "$instance_id" ] && [[ "$instance_id" != Error* ]]; then
            wait
            end_time=$(date +%s)
            creation_time=$((end_time - start_time))
            creation_succeeded=true
        else
            instance_id=$vm_name
            creation_time=-1
            creation_succeeded=false
        fi
    } || {
        instance_id=$vm_name
        creation_time=-2
        creation_succeeded=false
    }

    result="$test_details, \
        \"vm_id\": \"$instance_id\", \
        \"operation\": \"create_vm\", \
        \"time\": \"$creation_time\", \
        \"succeeded\": \"$creation_succeeded\" \
    }"

    mkdir -p $result_dir
    echo $result > "$result_dir/creation-$cloud-$vm_name-$vm_size-$(date +%s).json"

    if [[ "$creation_succeeded" == "true" ]]; then
        echo "$instance_id"
    fi
}

# Description:
#   This function is used to to measure the time it takes to delete a VM and save results in JSON format
#
# Parameters:
#   - $1: The cloud provider (e.g. azure, aws, gcp)
#   - $2: The name of the VM (e.g. vm-1-1233213123)
#   - $3: The region where the VM will be created (e.g. us-east1)
#   - $4: The resource group (e.g. my-resource-group)
#   - $5: The result directory where to place the results in JSON format
#   - $6: The test details in JSON format
#
# Notes:
#   - the Instance ID is returned if no errors occurred
#
# Usage: measure_delete_vm <cloud> <vm_name> <region> <resource_group> <result_dir> <test_details>
measure_delete_vm() {
    local cloud=$1
    local vm_name=$2
    local region=$3
    local resource_group=$4
    local result_dir=$5
    local test_details=$6

    {
        local start_time=$(date +%s)
        case $cloud in
            azure)
            vm=$(delete_vm "$vm_name" "$resource_group")
            ;;
            aws)
            vm=$(delete_ec2 "$vm_name" "$region")
            ;;
            gcp)
            vm=$(delete_vm "$vm_name" "$region")
            ;;
            *)
            exit 1 # cloud provider unknown
            ;;
        esac
        
        if [ -n "$vm" ] && [[ "$vm" != *Error* ]]; then
            wait
            end_time=$(date +%s)
            deletion_time=$((end_time - start_time))
            deletion_succeeded=true
        else
            deletion_time=-1
            deletion_succeeded=false
        fi
    } || {
        deletion_time=-2
        deletion_succeeded=false
    }

    result="$test_details, \
        \"vm_id\": \"$instance_id\", \
        \"operation\": \"delete_vm\", \
        \"time\": \"$deletion_time\", \
        \"succeeded\": \"$deletion_succeeded\" \
    }"

    mkdir -p $result_dir
    echo $result > "$result_dir/deletion-$cloud-$vm_name-$vm_size-$(date +%s).json"

    if [[ "$deletion_succeeded" == "true" ]]; then
        echo "$vm_name"
    fi
}
