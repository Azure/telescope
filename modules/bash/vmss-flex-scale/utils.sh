#!/bin/bash

# Description:
#   This function is used to generate a VMSS name
#
# Parameters:
#   - $1: The run id
#
# Notes:
#   - the VMSS name is truncated to 64 characters due to naming limitations
#
# Usage: get_vmss_name <run_id>
get_vmss_name() {
    local run_id=$1

    local vmss_name="vmss-$run_id"
    vmss_name="${vmss_name:0:64}"
    vmss_name="${vmss_name%-}"

    echo "$vmss_name"
}

# Description:
#   This function is used to measure the time it takes to create and delete a VMSS and save results in JSON format
#
# Parameters:
#   - $1: cloud: The cloud provider (e.g. azure, aws, gcp)
#   - $2: vmss_name: The name of the VMSS (e.g. vmss-1-1233213123)
#   - $3: vm_size: The size of the VM used in the VMSS (e.g. c3-highcpu-4)
#   - $4: vm_os: The OS identifier the VM will use (e.g. projects/ubuntu-os-cloud/global/images/ubuntu-2004-focal-v20240229)
#   - $5: instances: The number of VM instances in the VMSS (e.g. 1)
#   - $6: scale: Should the scenario scale up/down by one unit (e.g. false)
#   - $7: vm_scale_instances_target: The target number of instances to scale to (e.g. 10)
#   - $8: scaling_step: The number of instances to scale up/down by (e.g. 1)
#   - $9: region: The region where the VMSS will be created (e.g. us-east1)
#   - $10: run_id: The run id
#   - $11: network_security_group: The network security group (eg. my-nsg)
#   - $12: vnet_name: The virtual network name (e.g. my-vnet)
#   - $13: subnet: The subnet (e.g. my-subnet)
#   - $14: security_type: The security type (e.g. TrustedLaunch)
#   - $15: lt_name: The launch template name (e.g. my-launch-template)
#   - $16: result_dir: The result directory where to place the results in JSON format
#   - $17: tags: The tags to use (e.g. "owner=azure_devops,creation_time=2024-03-11T19:12:01Z")
#
# Usage: measure_create_delete_vmss <cloud> <vmss_name> <vm_size> <vm_os> <instances> <scale> <vm_scale_instances_target> <scaling_step> <run_id> <region> <network_security_group> <vnet_name> <subnet> <security_type> <lt_name> <result_dir> <tags>
measure_create_scale_delete_vmss() {
    local cloud=$1
    local vmss_name=$2
    local vm_size=$3
    local vm_os=$4
    local vm_instances=$5
    local scale=$6
    local vm_scale_instances_target=$7
    local scaling_step=$8
    local region=$9
    local run_id=${10}
    local network_security_group=${11}
    local vnet_name=${12}
    local subnet=${13}
    local security_type=${14}
    local lt_name=${15}
    local result_dir=${16}
    local tags=${17}

    local test_details="{ \
        \"cloud\": \"$cloud\", \
        \"name\": \"$vmss_name\", \
        \"vm_size\": \"$vm_size\", \
        \"vm_os\": \"$vm_os\", \
        \"vm_instances\": \"$vm_instances\", \
        \"scale\": \"$scale\", \
        \"vm_scale_instances_target\": \"$vm_scale_instances_target\", \
        \"scaling_step\": \"$scaling_step\", \
        \"region\": \"$region\", \
        \"network_security_group\": \"$network_security_group\", \
        \"vnet_name\": \"$vnet_name\", \
        \"subnet\": \"$subnet\", \
        \"security_type\": \"$security_type\""
    
    echo "Measuring $cloud VMSS creation/deletion for with the following details: 
        - VMSS name: $vmss_name
        - VM size: $vm_size
        - VM OS: $vm_os
        - Instances: $vm_instances
        - Scale: $scale
        - VM Scale Instances Target: $vm_scale_instances_target
        - Scaling Step: $scaling_step
        - Region: $region
        - Network Security Group: $network_security_group
        - VNet: $vnet_name
        - Subnet: $subnet
        - Security type: $security_type
        - Tags: $tags"

    set -x
    
    vmss_id=$(measure_create_vmss "$cloud" "$vmss_name" "$vm_size" "$vm_os" "$vm_instances" "$region" "$run_id" "$network_security_group" "$vnet_name" "$subnet" "$security_type" "$lt_name" "$result_dir" "$test_details" "$tags")

    if [ -n "$scale" ] && [ "$scale" == "True" ]; then
        for ((i=$((vm_instances + scaling_step)) ; i<=$vm_scale_instances_target; i+=$scaling_step)); do
            measure_scale_vmss "$cloud" "$vmss_name" "$region" "$run_id" "$i" "scale_up_vmss" "$result_dir" "$test_details"
        done

        for ((i=$((vm_scale_instances_target - scaling_step)); i>=$vm_instances; i-=$scaling_step)); do
            measure_scale_vmss "$cloud" "$vmss_name" "$region" "$run_id" "$i" "scale_down_vmss" "$result_dir" "$test_details"
        done
    fi

    if [ -n "$vmss_id" ] && [[ "$vmss_id" != Error* ]]; then
        vmss_id=$(measure_delete_vmss "$cloud" "$vmss_id" "$region" "$run_id" "$result_dir" "$test_details")
    fi

    if [[ "$cloud" == "aws" ]]; then
        delete_lt "$lt_name"
    fi
}

# Description:
#   This function is used to measure the time it takes to create a VMSS and save the results in JSON format
#
# Parameters:
#   - $1: cloud: The cloud provider (e.g. azure, aws, gcp)
#   - $2: vmss_name: The name of the VMSS (e.g. vmss-1-1233213123)
#   - $3: vm_size: The size of the VM used in the VMSS (e.g. c3-highcpu-4)
#   - $4: vm_os: The OS identifier the VM will use (e.g. projects/ubuntu-os-cloud/global/images/ubuntu-2004-focal-v20240229)
#   - $5: instances: The number of VM instances in the VMSS (e.g. 1)
#   - $6: region: The region where the VMSS will be created (e.g. us-east1)
#   - $7: run_id: The run id
#   - $8: network_security_group: The network security group (eg. my-nsg)
#   - $9: vnet_name: The virtual network name (e.g. my-vnet)
#   - $10: subnet: The subnet (e.g. my-subnet)
#   - $11: security_type: The security type (e.g. TrustedLaunch)
#   - $12: lt_name: The launch template name (e.g. my-launch-template)
#   - $13: result_dir: The result directory where to place the results in JSON format
#   - $14: test_details: The test details in JSON format
#   - $15: tags: The tags to use (e.g. "owner=azure_devops,creation_time=2024-03-11T19:12:01Z")
#
# Notes:
#   - the VMSS ID is returned if no errors occurred
#
# Usage: measure_create_vmss <cloud> <vmss_name> <vm_size> <vm_os> <vm_instances> <region> <run_id> <network_security_group> <vnet_name> <subnet> <security_type> <lt_name> <result_dir> <test_details> <tags>
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
    local lt_name=${12}
    local result_dir=${13}
    local test_details=${14}
    local tags=${15}

    local creation_succeeded=false
    local creation_time=-1
    local vmss_id="$vmss_name"
    local output_vmss_data="{ \"vmss_data\": {}}"

    if [[ "$cloud" == "aws" ]]; then
        security_group_id=$(aws ec2 describe-security-groups --filters "Name=tag:Name,Values=$network_security_group" --query "SecurityGroups[0].GroupId" --output text)
        subnet_id=$(aws ec2 describe-subnets --filters "Name=tag:Name,Values=$subnet" --query "Subnets[0].SubnetId" --output text)
    fi

    local start_time=$(date +%s)

    if [[ "$cloud" == "aws" ]]; then
        lt_id=$(create_lt "$lt_name" "$vm_size" "$vm_os" "$security_group_id" "$subnet_id" "$region")
    fi

    case $cloud in
        azure)
            vmss_data=$(create_vmss "$vmss_name" "$vm_size" "$vm_os" "$vm_instances" "$region" "$run_id" "$network_security_group" "$vnet_name" "$subnet" "$security_type" "$tags")
        ;;
        aws)
            vmss_data=$(create_asg "$vmss_name" "$vm_instances" "$vm_scale_instances_target" "$lt_name" "$region" "$tags")
            wait_for_desired_capacity "$vmss_name" "$vm_instances"
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
        \"vm_target_instances\": \"$vm_instances\", \
        \"operation\": \"create_vmss\", \
        \"time\": \"$creation_time\", \
        \"succeeded\": \"$creation_succeeded\" \
    }"

    mkdir -p "$result_dir"
    echo $result > "$result_dir/creation-$cloud-$vmss_name-$vm_instances-$(date +%s).json"

    if [[ "$creation_succeeded" == "true" ]]; then
        echo "$vmss_id"
    fi
}

# Description:
#   This function is used to measure the time it takes to scale a VMSS and save results in JSON format
#
# Parameters:
#   - $1: cloud: The cloud provider (e.g. azure, aws, gcp)
#   - $2: vmss_name: The name of the VMSS (e.g. vmss-1-1233213123)
#   - $3: region: The region where the VMSS will be created (e.g. us-east1)
#   - $4: run_id: The run id
#   - $5: new_capacity: The new capacity for the VMSS (e.g. 20)
#   - $6: scale_type: A parameter that lets us know if we need to scale up or down
#   - $7: result_dir: The result directory where to place the results in JSON format
#   - $8: test_details: The test details in JSON format
#
# Notes:
#   - the VMSS ID is returned if no errors occurred
#
# Usage: measure_delete_vmss <cloud> <vmss_name> <region> <run_id> <new_capacity> <scale_type> <result_dir> <test_details>
measure_scale_vmss() {
    local cloud=$1
    local vmss_name=$2
    local region=$3
    local run_id=$4
    local new_capacity=$5
    local scale_type=$6
    local result_dir=$7
    local test_details=$8

    local scaling_succeeded=false
    local scaling_time=-1
    local output_vmss_data="{ \"vmss_data\": {}}"

    local start_time=$(date +%s)
    case $cloud in
        azure)
            vmss_data=$(scale_vmss "$vmss_name" "$run_id" "$new_capacity")
        ;;
        aws)
            vmss_data=$(scale_asg "$vmss_name" "$new_capacity")
            wait_for_desired_capacity "$vmss_name" "$new_capacity"
            wait_for_scaling_activities "$vmss_name"
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
            scaling_time=$((end_time - start_time))
            scaling_succeeded=true
        else
            temporary_vmss_data=$(echo "$vmss_data" | jq -r '.vmss_data')
            if [[ -n "$temporary_vmss_data" ]]; then
                output_vmss_data=$vmss_data
            fi
        fi
    fi

    result="$test_details, \
        \"vmss_id\": \"$vmss_name\", \
        \"vmss_data\": $(jq -c -n \
          --argjson vmss_data "$(echo "$output_vmss_data" | jq -r '.vmss_data')" \
          '$vmss_data'), \
        \"vm_target_instances\": \"$new_capacity\", \
        \"operation\": \"$scale_type\", \
        \"time\": \"$scaling_time\", \
        \"succeeded\": \"$scaling_succeeded\" \
    }"

    mkdir -p "$result_dir"
    echo $result > "$result_dir/scaling-$cloud-$vmss_name-$new_capacity-$(date +%s).json"

    if [[ "$scaling_succeeded" == "true" ]]; then
        echo "$vmss_name"
    fi
}

# Description:
#   This function is used to to measure the time it takes to delete a VMSS and save results in JSON format
#
# Parameters:
#   - $1: cloud: The cloud provider (e.g. azure, aws, gcp)
#   - $2: vmss_name: The name of the VMSS (e.g. vmss-1-1233213123)
#   - $3: region: The region where the VMSS will be created (e.g. us-east1)
#   - $4: run_id: The run id
#   - $5: result_dir: The result directory where to place the results in JSON format
#   - $6: test_details: The test details in JSON format
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
            vmss_data=$(delete_asg "$vmss_name")
            wait_until_no_autoscaling_groups $vmss_name
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
        \"vm_target_instances\": \"0\", \
        \"operation\": \"delete_vmss\", \
        \"time\": \"$deletion_time\", \
        \"succeeded\": \"$deletion_succeeded\" \
    }"

    mkdir -p "$result_dir"
    echo $result > "$result_dir/deletion-$cloud-$vmss_name-$vm_instances-$(date +%s).json"

    if [[ "$deletion_succeeded" == "true" ]]; then
        echo "$vmss_name"
    fi
}