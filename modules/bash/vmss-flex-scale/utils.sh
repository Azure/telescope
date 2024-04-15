#!/bin/bash

source /mount/modules/bash/vmss-flex-scale/azure.sh

# Description:
#   This function is used to generate a VMSS name
#
# Parameters:
#   - $1: The index of the VMSS
#   - $2: The run id
#
# Notes:
#   - the VMSS name is truncated to 15 characters due to Windows limitations
#
# Usage: get_vmss_name <index> <run_id>
get_vmss_name() {
    local i=$1
    local run_id=$2

    local vmss_name="vm-$i-$run_id"
    vmss_name="${vmss_name:0:15}"
    vmss_name="${vmss_name%-}"

    echo "$vmss_name"
}

# Description:
#   This function is used to to measure the time it takes to create and delete a VM and save results in JSON format
#
# Parameters:
#   - $1: The cloud provider (e.g. azure, aws, gcp)
#   - $2: The name of the VMSS (e.g. vmss-1-1233213123)
#   - $3: The size of the VM used in the VMS (e.g. c3-highcpu-4)
#   - $4: The OS identifier the VM will use (e.g. projects/ubuntu-os-cloud/global/images/ubuntu-2004-focal-v20240229)
#   - $5: The run id
#   - $6: The region where the VMSS will be created (e.g. us-east1)
#   - $7: The subnet (e.g. my-subnet)
#   - $8: The security type (e.g. TrustedLaunch)
#   - $9: The result directory where to place the results in JSON format
#   - $10: The tags to use (e.g. "owner=azure_devops,creation_time=2024-03-11T19:12:01Z")
#
# Usage: measure_create_delete_vmss <cloud> <vm_name> <vm_size> <vm_os> <run_id> <region> <subnet> <security_type> <result_dir> <tags>
measure_create_delete_vmss() {
    local cloud=$1
    local vmss_name=$2
    local vm_os=$3
    local vm_size=$4
    local region=$5
    local run_id=$6
    local network_security_group=$7
    local vnet_name=$8
    local subnet=$9
    local security_type=${10}
    local result_dir=${11}
    local tags=${12}

    local test_details="{ \
        \"cloud\": \"$cloud\", \
        \"name\": \"$vmss_name\", \
        \"size\": \"$vm_os\", \
        \"os\": \"$vm_size\", \
        \"region\": \"$region\", \
        \"network_security_group\": \"$network_security_group\", \
        \"vnet_name\": \"$vnet_name\", \
        \"subnet\": \"$subnet\", \
        \"security_type\": \"$security_type\""
    
    echo "Measuring $cloud VMSS creation/deletion for with the following details: 
        - VMSS name: $vmss_name
        - VM size: $vm_size
        - VM OS: $vm_os
        - Region: $region
        - Network Security Group: $network_security_group
		- VNet: $vnet_name
        - Subnet: $subnet
        - Security type: $security_type
        - Tags: $tags"
    
    vmss_id=$(measure_create_vmss "$cloud" "$vmss_name" "$vm_os" "$vm_size" "$run_id" "$region" "$subnet" "$security_type" "$result_dir" "$test_details" "$tags")

    if [ -n "$vmss_id" ] && [[ "$vmss_id" != Error* ]]; then
        vmss_id=$(measure_delete_vmss "$cloud" "$vmss_id" "$region" "$run_id" "$result_dir" "$test_details")
    fi

}

# Description:
#   This function is used to measure the time it takes to create a VMSS and save the results in JSON format
#
# Parameters:
#   - $1: The cloud provider (e.g. azure, aws, gcp)
#   - $2: The name of the VMSS (e.g. vmss-test)
#   - $3: The size of the VM (e.g. c3-highcpu-4)
#   - $4: The OS identifier the VM will use (e.g. projects/ubuntu-os-cloud/global/images/ubuntu-2004-focal-v20240229)
#   - $5: The region where the VM will be created (e.g. us-east1)
#   - $6: Optional NIC to be used for VM creation/deletion measurement
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
# Usage: measure_create_vm <cloud> <vm_name> <vm_size> <vm_os> <region> <nic> <run_id> <security_group> <subnet> <accelerator> <security_type> <storage_type> <result_dir> <test_details> <tags>
measure_create_vmss() {
    local cloud=$1
    local vmss_name=$2
    local vm_os=$3
    local vm_size=$4
    local region=$5
    local run_id=$6
    local network_security_group=$7
    local vnet_name=$8
    local subnet=$9
    local security_type=${10}
    local result_dir=${11}
    local test_details=${12}
    local tags=${13}

    local creation_succeeded=false
    local creation_time=-1
    local vmss_id="$vmss_name"
    local output_vmss_data="{ \"vmss_data\": {}}"

    local start_time=$(date +%s)
    case $cloud in
        azure)
            vmss_data=$(create_vmss "$vmss_name" "$vm_size" "$vm_os" "$region" "$run_id" "$network_security_group" "$vnet_name" "$subnet" "$security_type" "$tags")
        ;;
        aws)
            # AWS Method call
        ;;
        gcp)
            # GCP Method call
        ;;
        *)
            exit 1 # cloud provider unknown
        ;;
    esac

    wait
    end_time=$(date +%s)

    if [[ -n "$vmss_data" ]]; then
        succeeded=$(echo "$vmss_data" | jq -r '.succeeded')
        if [[ "$succeeded" == "true" ]]; then
            output_vmss_data=$vmss_data
            vmss_id=$(echo "$vmss_data" | jq -r '.vmss_name')
            creation_time=$((end_time - start_time))
            creation_succeeded=true
        else
            temporary_vmss_data=$(echo "$vmss_data" | jq -r '.vmss_data')
            if [[ -n "$temporary_vmss_data" ]]; then
                output_vmss_data=$vmss_data
            fi
        fi
    fi

    result="$test_details, \
        \"vmss_id\": \"$vmss_id\", \
        \"vmss_data\": $(jq -c -n \
          --argjson vmss_data "$(echo "$output_vmss_data" | jq -r '.vmss_data')" \
          '$vmss_data'), \
        \"operation\": \"create_vmss\", \
        \"time\": \"$creation_time\", \
        \"succeeded\": \"$creation_succeeded\" \
    }"

    mkdir -p "$result_dir"
    echo $result > "$result_dir/creation-$cloud-$vmss_name-$vmss_size-$(date +%s).json"

    if [[ "$creation_succeeded" == "true" ]]; then
        echo "$vmss_id"
    fi
}

measure_delete_vmss() {
    local cloud=$1
    local vmss_name=$2
    local region=$3
    local run_id=$4
    local result_dir=$5
    local test_details=$6

    local deletion_succeeded=false
    local deletion_time=-1
    local output_vmss_data="{ \"vmss_data\": {}}"

    local start_time=$(date +%s)
    case $cloud in
        azure)
            vmss_data=$(delete_vmss "$vmss_name" "$run_id")
        ;;
        aws)
            vmss_data=$(delete_ec2 "$vmss_name" "$region")
        ;;
        gcp)
            vmss_data=$(delete_vm "$vmss_name" "$region")
        ;;
        *)
            exit 1 # cloud provider unknown
        ;;
    esac

    wait
    end_time=$(date +%s)

    if [[ -n "$vmss_data" ]]; then
        succeeded=$(echo "$vmss_data" | jq -r '.succeeded')
        if [[ "$succeeded" == "true" ]]; then
            output_vmss_data=$vmss_data
            deletion_time=$((end_time - start_time))
            deletion_succeeded=true
        else
            temporary_vmss_data=$(echo "$vmss_data" | jq -r '.vmss_data')
            if [[ -n "$temporary_vmss_data" ]]; then
                output_vmss_data=$vmss_data
            fi
        fi
    fi

    result="$test_details, \
        \"vmss_id\": \"$vmss_name\", \
        \"operation\": \"delete_vmss\", \
        \"time\": \"$deletion_time\", \
        \"succeeded\": \"$deletion_succeeded\" \
    }"

    mkdir -p "$result_dir"
    echo $result > "$result_dir/deletion-$cloud-$vmss_name-$vmss_size-$(date +%s).json"

    if [[ "$deletion_succeeded" == "true" ]]; then
        echo "$vmss_name"
    fi
}