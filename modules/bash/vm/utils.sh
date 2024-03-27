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
#   - $6: Whether to pre-create the NIC or let it be part of the VM creation/deletion measurement (e.g. true)
#   - $7: The run id
#   - $8: The security group (e.g. my-security-group)
#   - $9: The subnet (e.g. my-subnet)
#   - $10: [optional] The accelerator to use (e.g. count=8,type=nvidia-h100-80gb, default value is empty)
#   - $11: The security type (e.g. TrustedLaunch)
#   - $12: The storage type (e.g. Premium_LRS)
#   - $13: The result directory where to place the results in JSON format
#   - $14: The tags to use (e.g. "owner=azure_devops,creation_time=2024-03-11T19:12:01Z")
#
# Usage: measure_create_delete_vm <cloud> <vm_name> <vm_size> <vm_os> <region> <precreate_nic> <run_id> <security_group> <subnet> <accelerator> <security_type> <storage_type> <result_dir> <tags>
measure_create_delete_vm() {
    local cloud=$1
    local vm_name=$2
    local vm_size=$3
    local vm_os=$4
    local region=$5
    local precreate_nic=$6
    local run_id=$7
    local security_group=$8
    local subnet=$9
    local accelerator=${10}
    local security_type=${11}
    local storage_type=${12}
    local result_dir=${13}
    local tags=${14}

    local test_details="{ \
        \"cloud\": \"$cloud\", \
        \"name\": \"$vm_name\", \
        \"size\": \"$vm_size\", \
        \"os\": \"$vm_os\", \
        \"region\": \"$region\", \
        \"precreate_nic\": \"$precreate_nic\", \
        \"accelerator\": \"$accelerator\", \
        \"security_type\": \"$security_type\", \
        \"storage_type\": \"$storage_type\""
    
    echo "Measuring $cloud VM creation/deletion for with the following details: 
- VM name: $vm_name
- VM size: $vm_size
- VM OS: $vm_os
- Region: $region
- Precreate NIC: $precreate_nic
- Security group: $security_group
- Subnet: $subnet
- Accelerator: $accelerator
- Security type: $security_type
- Storage type: $storage_type
- Tags: $tags"
    
    vm_id=$(measure_create_vm "$cloud" "$vm_name" "$vm_size" "$vm_os" "$region" "$precreate_nic" "$run_id" "$security_group" "$subnet" "$accelerator" "$security_type" "$storage_type" "$result_dir" "$test_details" "$tags")

    if [ -n "$vm_id" ] && [[ "$vm_id" != Error* ]]; then
        vm_id=$(measure_delete_vm "$cloud" "$vm_id" "$region" "$precreate_nic" "$run_id" "$result_dir" "$test_details")
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
#   - $6: Whether to pre-create the NIC or let it be part of the VM creation/deletion measurement (e.g. true)
#   - $7: The run id
#   - $8: The security group (e.g. my-security-group)
#   - $9: The subnet (e.g. my-subnet)
#   - $10: [optional] The accelerator to use (e.g. count=8,type=nvidia-h100-80gb, default value is empty)
#   - $11: The security type (e.g. TrustedLaunch)
#   - $12: The storage type (e.g. Premium_LRS)
#   - $13: The result directory where to place the results in JSON format
#   - $14: The test details in JSON format
#   - $15: The tags to use (e.g. "owner=azure_devops,creation_time=2024-03-11T19:12:01Z")
#
# Notes:
#   - the VM ID is returned if no errors occurred
#
# Usage: measure_create_vm <cloud> <vm_name> <vm_size> <vm_os> <region> <precreate_nic> <run_id> <security_group> <subnet> <accelerator> <security_type> <storage_type> <result_dir> <test_details> <tags>
measure_create_vm() {
    local cloud=$1
    local vm_name=$2
    local vm_size=$3
    local vm_os=$4
    local region=$5
    local precreate_nic=$6
    local run_id=$7
    local security_group=$8
    local subnet=$9
    local accelerator=${10}
    local security_type=${11}
    local storage_type=${12}
    local result_dir=${13}
    local test_details=${14}
    local tags=${15}

    local creation_succeeded=false
    local creation_time=-1
    local vm_id="$vm_name"
    local output_vm_data="{ \"vm_data\": {}}"

    {
        local nic=""
        if [[ "$precreate_nic" == "true" ]]; then
            # we will use defaults here to not clobber the method signature, but we may want to parameterize these in the future
            local nic_name="nic_$vm_name"
            case $cloud in
                azure)
                    local vnet="create-delete-vm-vnet"
                    subnet="create-delete-vm-subnet"
                    local accelerated_networking=true
                    nic=$(create_nic "$nic_name" "$run_id" "$vnet" "$subnet" "$accelerated_networking" "$tags")
                ;;
                aws)
                    local nic_tags="${tags/ResourceType=instance/ResourceType=network-interface}"
                    nic=$(create_nic "$nic_name" "$subnet" "$security_group" "$nic_tags")
                ;;
                gcp)
                    nic=$(create_nic_instance_template "it_$nic_name" "$region" "$subnet" "$tags")
                ;;
                *)
                    exit 1 # cloud provider unknown
                ;;
            esac
        fi

        local start_time=$(date +%s)
        case $cloud in
            azure)
                vm_data=$(create_vm "$vm_name" "$vm_size" "$vm_os" "$region" "$run_id" "$nic" "$security_type" "$storage_type" "$tags")
            ;;
            aws)
                vm_data=$(create_ec2 "$vm_name" "$vm_size" "$vm_os" "$region" "$nic" "$subnet" "$tags")
            ;;
            gcp)
                vm_data=$(create_vm "$vm_name" "$vm_size" "$vm_os" "$region" "$nic" "$accelerator" "$tags")
            ;;
            *)
                exit 1 # cloud provider unknown
            ;;
        esac

        wait
        end_time=$(date +%s)

        if [[ -n "$vm_data" ]]; then
            succeeded=$(echo "$vm_data" | jq -r '.succeeded')
            if [[ "$succeeded" == "true" ]]; then
                output_vm_data=$vm_data
                vm_id=$(echo "$vm_data" | jq -r '.vm_name')
                creation_time=$((end_time - start_time))
                creation_succeeded=true
            else
                temporary_vm_data=$(echo "$vm_data" | jq -r '.vm_data')
                if [[ -n "$temporary_vm_data" ]]; then
                    output_vm_data=$vm_data
                fi
            fi
        fi
    } || {
        creation_time=-2
    }

    result="$test_details, \
        \"vm_id\": \"$vm_id\", \
        \"vm_data\": $(jq -c -n \
          --argjson vm_data "$(echo "$output_vm_data" | jq -r '.vm_data')" \
          '$vm_data'), \
        \"operation\": \"create_vm\", \
        \"time\": \"$creation_time\", \
        \"succeeded\": \"$creation_succeeded\" \
    }"

    mkdir -p $result_dir
    echo $result > "$result_dir/creation-$cloud-$vm_name-$vm_size-$(date +%s).json"

    if [[ "$creation_succeeded" == "true" ]]; then
        echo "$vm_id"
    fi
}

# Description:
#   This function is used to to measure the time it takes to delete a VM and save results in JSON format
#
# Parameters:
#   - $1: The cloud provider (e.g. azure, aws, gcp)
#   - $2: The name of the VM (e.g. vm-1-1233213123)
#   - $3: The region where the VM will be created (e.g. us-east1)
#   - $4: Whether there was a pre-created NIC that needs to be removed or let it be part of the VM creation/deletion measurement (e.g. true)
#   - $5: The run id
#   - $6: The result directory where to place the results in JSON format
#   - $7: The test details in JSON format
#
# Notes:
#   - the VM ID is returned if no errors occurred
#
# Usage: measure_delete_vm <cloud> <vm_name> <region> <precreate_nic> <run_id> <result_dir> <test_details>
measure_delete_vm() {
    local cloud=$1
    local vm_name=$2
    local region=$3
    local precreate_nic=$4
    local run_id=$5
    local result_dir=$6
    local test_details=$7
    
    local deletion_succeeded=false
    local deletion_time=-1
    local output_vm_data="{ \"vm_data\": {}}"

    {
        if [[ "$precreate_nic" == "true" ]] && [[ "$cloud" == "aws" ]]; then
            nic=$(aws ec2 describe-instances --instance-ids "$vm_name" --output text --query 'Reservations[0].Instances[0].NetworkInterfaces[0].NetworkInterfaceId')
        fi

        local start_time=$(date +%s)
        case $cloud in
            azure)
                vm_data=$(delete_vm "$vm_name" "$run_id")
            ;;
            aws)
                vm_data=$(delete_ec2 "$vm_name" "$region")
            ;;
            gcp)
                vm_data=$(delete_vm "$vm_name" "$region")
            ;;
            *)
                exit 1 # cloud provider unknown
            ;;
        esac

        wait
        end_time=$(date +%s)

        if [[ -n "$vm_data" ]]; then
            succeeded=$(echo "$vm_data" | jq -r '.succeeded')
            if [[ "$succeeded" == "true" ]]; then
                output_vm_data=$vm_data
                deletion_time=$((end_time - start_time))
                deletion_succeeded=true
            else
                temporary_vm_data=$(echo "$vm_data" | jq -r '.vm_data')
                if [[ -n "$temporary_vm_data" ]]; then
                    output_vm_data=$temporary_vm_data
                fi
            fi
        fi
        
        if [[ "$precreate_nic" == "true" ]] && [[ "$cloud" == "aws" ]]; then
            deleted_nic=$(delete_nic "$nic")
        fi
    } || {
        deletion_time=-2
    }

    result="$test_details, \
        \"vm_id\": \"$vm_name\", \
        \"vm_data\": $(jq -c -n \
          --argjson vm_data "$(echo "$output_vm_data" | jq -r '.vm_data')" \
          '$vm_data'), \
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
