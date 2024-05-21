#!/bin/bash

# Description:
#   This function is used to generate a VMSS name
#
# Parameters:
#   - $1: The run id
#
# Notes:
#   - the VMSS name is truncated to 15 characters due to Windows limitations
#
# Usage: get_vmss_name <run_id>
get_vmss_name() {
    local run_id=$1

    local vmss_name="vmss-$run_id"
    vmss_name="${vmss_name:0:15}"
    vmss_name="${vmss_name%-}"

    echo "$vmss_name"
}

# Description:
#   This function is used to measure the time it takes to create and delete a VMSS and save results in JSON format
#
# Parameters:
#   - $1: The cloud provider (e.g. azure, aws, gcp)
#   - $2: The name of the VMSS (e.g. vmss-1-1233213123)
#   - $3: The size of the VM used in the VMSS (e.g. c3-highcpu-4)
#   - $4: The OS identifier the VM will use (e.g. projects/ubuntu-os-cloud/global/images/ubuntu-2004-focal-v20240229)
#   - $5: The number of VM instances in the VMSS (e.g. 1)
#   - $6: The region where the VMSS will be created (e.g. us-east1)
#   - $7: The run id
#   - $8: The network security group (eg. my-nsg)
#   - $9: The virtual network name (e.g. my-vnet)
#   - $10: The subnet (e.g. my-subnet)
#   - $11: The security type (e.g. TrustedLaunch)
#   - $12: The result directory where to place the results in JSON format
#   - $13: The tags to use (e.g. "owner=azure_devops,creation_time=2024-03-11T19:12:01Z")
#
# Usage: measure_create_delete_vmss <cloud> <vmss_name> <vm_size> <vm_os> <instances> <run_id> <region> <network_security_group> <vnet_name> <subnet> <security_type> <result_dir> <tags>
measure_create_delete_vmss() {
    local cloud=$1
    local vmss_name=$2
    local vm_size=$3
    local vm_os=$4
    local vm_instances=$5
    local region=$6
    local run_id=$7
    local network_security_group=$8
    local vnet_name=$9
    local subnet=${10}
    local security_type=${11}
    local result_dir=${12}
    local tags=${13}

    local test_details="{ \
        \"cloud\": \"$cloud\", \
        \"name\": \"$vmss_name\", \
        \"vm_size\": \"$vm_size\", \
        \"vm_os\": \"$vm_os\", \
        \"vm_instances\": \"$vm_instances\", \
        \"region\": \"$region\", \
        \"network_security_group\": \"$network_security_group\", \
        \"vnet_name\": \"$vnet_name\", \
        \"subnet\": \"$subnet\", \
        \"security_type\": \"$security_type\""
    
    echo "Measuring $cloud VMSS creation/deletion for with the following details: 
        - VMSS name: $vmss_name
        - VM size: $vm_size
        - VM OS: $vm_os
        - VM instances: $vm_instances
        - Region: $region
        - Network Security Group: $network_security_group
		- VNet: $vnet_name
        - Subnet: $subnet
        - Security type: $security_type
        - Tags: $tags"
    
    vmss_id=$(measure_create_vmss "$cloud" "$vmss_name" "$vm_size" "$vm_os" "$vm_instances" "$region" "$run_id" "$network_security_group" "$vnet_name" "$subnet" "$security_type" "$result_dir" "$test_details" "$tags")

    if [ -n "$vmss_id" ] && [[ "$vmss_id" != Error* ]]; then
        vmss_id=$(measure_delete_vmss "$cloud" "$vmss_id" "$region" "$run_id" "$result_dir" "$test_details")
    fi

}

# Description:
#   This function is used to measure the time it takes to create a VMSS and save the results in JSON format
#
# Parameters:
#   - $1: The cloud provider (e.g. azure, aws, gcp)
#   - $2: The name of the VMSS (e.g. vmss-1-1233213123)
#   - $3: The size of the VM used in the VMSS (e.g. c3-highcpu-4)
#   - $4: The OS identifier the VM will use (e.g. projects/ubuntu-os-cloud/global/images/ubuntu-2004-focal-v20240229)
#   - $5: The number of VM instances in the VMSS (e.g. 1)
#   - $6: The region where the VMSS will be created (e.g. us-east1)
#   - $7: The run id
#   - $8: The network security group (eg. my-nsg)
#   - $9: The virtual network name (e.g. my-vnet)
#   - $10: The subnet (e.g. my-subnet)
#   - $11: The security type (e.g. TrustedLaunch)
#   - $12: The result directory where to place the results in JSON format
#   - $13: The test details in JSON format
#   - $14: The tags to use (e.g. "owner=azure_devops,creation_time=2024-03-11T19:12:01Z")
#
# Notes:
#   - the VMSS ID is returned if no errors occurred
#
# Usage: measure_create_vmss <cloud> <vmss_name> <vm_size> <vm_os> <vm_instances> <region> <run_id> <network_security_group> <vnet_name> <subnet> <security_type> <result_dir> <test_details> <tags>
measure_create_vmss() {
    local cloud=$1
    local vmss_name=$2
    local vm_size=$3
    local vm_os=$4
    local vm_instances=$5
    local region=$6
    local run_id=$7
    local network_security_group=$8
    local vnet_name=$9
    local subnet=${10}
    local security_type=${11}
    local result_dir=${12}
    local test_details=${13}
    local tags=${14}

    local creation_succeeded=false
    local creation_time=-1
    local vmss_id="$vmss_name"
    local output_vmss_data="{ \"vmss_data\": {}}"

    local start_time=$(date +%s)
    case $cloud in
        azure)
            vmss_data=$(create_vmss "$vmss_name" "$vm_size" "$vm_os" "$vm_instances" "$region" "$run_id" "$network_security_group" "$vnet_name" "$subnet" "$security_type" "$tags")
        ;;
        aws)
            # AWS Method call
            #end time
            # describe for data
            echo "AWS not implemented yet."
            exit 1
        ;;
        gcp)
            # GCP Method call
            echo "GCP not implemented yet."
            exit 1
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

# Description:
#   This function is used to to measure the time it takes to delete a VMSS and save results in JSON format
#
# Parameters:
#   - $1: The cloud provider (e.g. azure, aws, gcp)
#   - $2: The name of the VMSS (e.g. vmss-1-1233213123)
#   - $3: The region where the VMSS will be created (e.g. us-east1)
#   - $4: The run id
#   - $5: The result directory where to place the results in JSON format
#   - $6: The test details in JSON format
#
# Notes:
#   - the VMSS ID is returned if no errors occurred
#
# Usage: measure_delete_vmss <cloud> <vmss_name> <region> <run_id> <result_dir> <test_details>
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