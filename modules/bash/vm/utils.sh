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

    echo "$vm_name"
}

# Description:
#   This function is used to pre-create a NIC and PIP if needed
#
# Parameters:
#   - $1: The cloud provider (e.g. azure, aws, gcp)
#   - $2: The name of the VM (e.g. vm-1-1233213123)
#   - $3: The run id
#   - $4: The region where the VM will be created (e.g. us-east1)
#   - $5: The security group (e.g. my-security-group)
#   - $6: The subnet (e.g. my-subnet)
#   - $7: The tags to use (e.g. "owner=azure_devops,creation_time=2024-03-11T19:12:01Z")
#   - $8: Whether to pre-create the NIC and PIP or let them be part of the VM creation/deletion measurement (e.g. true)
#
# Notes:
#   - the NIC name and Public IP are returned if no errors occurred
#
# Usage: precreate_nic_and_pip_if_needed <cloud> <vm_name> <run_id> <region> <security_group> <subnet> <tags> <precreate_nic>
precreate_nic_and_pip_if_needed()
{
    local cloud=$1
    local vm_name=$2
    local run_id=$3
    local region=$4
    local security_group=$5
    local subnet=$6
    local tags=$7
    local precreate_nic_and_pip=$8

    local nic=""
    local pip=""
    if [[ "$precreate_nic" == "true" ]]; then
        # we will use defaults here to not clobber the method signature, but we may want to parameterize these in the future
        local nic_name="nic_$vm_name"
        local pip_name="pip_$vm_name"

        case $cloud in
            azure)
                local vnet="create-delete-vm-vnet"
                local nsg="create-delete-vm-nsg"
                subnet="create-delete-vm-subnet"
                local accelerated_networking=true
                pip=$(create_pip "$run_id" "$pip_name" "$region" "$tags")
                pip_id=$pip_name
                nic=$(create_nic "$nic_name" "$run_id" "$pip_name" "$nsg" "$vnet" "$subnet" "$accelerated_networking" "$tags")
            ;;
            aws)
                local pip_tags="${tags/ResourceType=instance/ResourceType=elastic-ip}"
                local nic_tags="${tags/ResourceType=instance/ResourceType=network-interface}"
                pip_data=$(create_pip "$region" "$pip_tags")
                pip_id=$(echo "$pip_data" | jq -r '.AllocationId')
                pip=$(echo "$pip_data" | jq -r '.PublicIp')
                nic=$(create_nic "$nic_name" "$subnet" "$security_group" "$pip_id" "$nic_tags")
            ;;
            gcp)
                # TODO: this will need to be reviewed once we have the GCP implementation
                nic=$(create_nic_instance_template "it_$nic_name" "$region" "$subnet" "$tags")
            ;;
            *)
                exit 1 # cloud provider unknown
            ;;
        esac
    fi

    echo $(jq -c -n \
        --arg nic "$nic" \
        --arg pip_id "$pip_id" \
        --arg pip "$pip" \
    '{nic: $nic, pip: {id: $pip_id, ip: $pip}}')
}

# Description:
#   This function is used to delete a NIC and PIP if needed
#
# Parameters:
#   - $1: The cloud provider (e.g. azure, aws, gcp)
#   - $2: The NIC name
#   - $3: The PIP name
#   - $4: The run id
#
# Usage: delete_nic_and_pip_if_needed <cloud> <nic_name> <pip_name> <run_id>
delete_nic_and_pip_if_needed() {
    local cloud=$1
    local nic_name=$2
    local pip_name=$3
    local run_id=$4

    if [[ -n "$nic_name" ]] && [[ "$cloud" == "aws" ]]; then
        delete_nic "$nic_name"
    fi

    if [[ -n "$pip_name" ]]; then
        delete_pip "$pip_name" "$nic_name" "$run_id"
    fi
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
#   - #13: The port to use for pinging the VM (e.g. 3389)
#   - $14: The timeout to wait for a VM creation operation to complete
#   - $15: The result directory where to place the results in JSON format
#   - $16: The tags to use (e.g. "owner=azure_devops,creation_time=2024-03-11T19:12:01Z")
#
# Usage: measure_create_delete_vm <cloud> <vm_name> <vm_size> <vm_os> <region> <precreate_nic> <run_id> <security_group> <subnet> <accelerator> <security_type> <storage_type> <port> <timeout> <result_dir> <tags
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
    local port=${13}
    local timeout=${14}
    local result_dir=${15}
    local tags=${16}

    local test_details="{ \
        \"cloud\": \"$cloud\", \
        \"name\": \"$vm_name\", \
        \"size\": \"$vm_size\", \
        \"os\": \"$vm_os\", \
        \"region\": \"$region\", \
        \"precreate_nic\": \"$precreate_nic\", \
        \"accelerator\": \"$accelerator\", \
        \"security_type\": \"$security_type\", \
        \"storage_type\": \"$storage_type\", \
        \"timeout\": \"$timeout\""
    
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
- Timeout: $timeout
- Tags: $tags"
    
    nic_and_pip=$(precreate_nic_and_pip_if_needed "$cloud" "$vm_name" "$run_id" "$region" "$security_group" "$subnet" "$tags" "$precreate_nic")
    nic=$(echo "$nic_and_pip" | jq -r '.nic')
    pip=$(echo "$nic_and_pip" | jq -r '.pip.ip')
    pip_id=$(echo "$nic_and_pip" | jq -r '.pip.id')

    pip=""
    
    if [[ -z "$nic" ]] || [[ -z "$pip" ]]; then
      local status_file="/tmp/test-info/$vm_name.json"
      echo "{\"succeeded\": false, \"error_message\": No NIC or PIP could be created.}" > "$status_file"
      exit 1
    fi

    vm_id=$(measure_create_vm "$cloud" "$vm_name" "$vm_size" "$vm_os" "$region" "$nic" "$pip" "$port" "$run_id" "$security_group" "$subnet" "$accelerator" "$security_type" "$storage_type" "$timeout" "$result_dir" "$test_details" "$tags")

    vm_id=$(measure_delete_vm "$cloud" "$vm_id" "$region" "$run_id" "$result_dir" "$test_details")

    delete_nic=$(delete_nic_and_pip_if_needed "$cloud" "$nic" "$pip_id" "$run_id")
}

# Description:
#   This function is used to to measure the time it takes to install CSE script for custom script extension on a created VM and save results in JSON format
#
# Parameters:
#   - $1: The cloud provider (e.g. azure, aws, gcp)
#   - $2: The run id
#   - $3: The result directory where to place the results in JSON format
#   - $4: The region
#   - $5: The name of the VM
#   - $6: [optional] The script command to be executed after installation (default: 'echo "Hello world"')
#
# Usage: measure_vm_extension <cloud> <run_id> <result_dir> <region> <vm_name> [command]
measure_vm_extension() {
    local cloud=$1
    local run_id=$2
    local result_dir=$3
    local region=$4
    local vm_name=$5
    local command=${6:-""}
    local result=""
    local installation_succedded="false"
    local installation_time=0

    local start_time=$(date +%s)
    echo "Measuring $cloud VM extension installation for $vm_name. Started at $start_time."

    case $cloud in
        azure)
            extension_data=$(install_vm_extension "$vm_name" "$run_id" "$command")
        ;;
        aws)
            extension_data=$(install_ec2_extension "$vm_name" "$region" "$command")
        ;;
        *)
            exit 1 # cloud provider unknown/not implemented
        ;;
    esac
    
    wait
    local end_time=$(date +%s)
    echo "Finished $cloud VM extension installation for $vm_name. Ended at $end_time."

    if [[ -n "$extension_data" ]]; then
        succeeded=$(jq -r '.succeeded' <<< "$extension_data")
        if [[ "$succeeded" == "true" ]]; then
            output_extension_data=$extension_data
            installation_time=$((end_time - start_time))
            installation_succedded="true"
        else
            temporary_extension_data=$(jq -r '.data' <<< "$extension_data")
            if [[ -n "$temporary_extension_data" ]]; then
                output_extension_data=$extension_data
            fi
        fi
    fi

    result="{\
        \"operation\": \"install_vm_extension\", \
        \"succeeded\": \"$installation_succedded\", \
        \"extension_data\": $(jq -c -n \
          --argjson extension_data "$(jq -r '.data' <<< "$output_extension_data")" \
          '$extension_data'), \
        \"time\": \"$installation_time\" \
    }"

    mkdir -p $result_dir
    echo $result > "$result_dir/vm-extension-$cloud-$vm_name-$(date +%s).json"
    echo $result
}

# Description:
#   This function is used to to measure the time it takes to run a command on a created VM and save results in JSON format
#
# Parameters:
#   - $1: The cloud provider (e.g. azure, aws, gcp)
#   - $2: The run id
#   - $3: The result directory where to place the results in JSON format
#   - $4: The region
#   - $5: The name of the VM
#   - $6: [optional] The script command to be executed (default: 'echo "Hello world"')
#
# Usage: measure_run_command <cloud> <run_id> <result_dir> <region> <vm_name> [command]
measure_vm_run_command() {
    local cloud=$1
    local run_id=$2
    local result_dir=$3
    local region=$4
    local vm_name=$5
    local command=${6:-""}
    local result=""
    local installation_succedded="false"
    local installation_time=0

    local start_time=$(date +%s)
    echo "Measuring $cloud VM RunCommand for $vm_name. Started at $start_time."

    case $cloud in
        azure)
            run_command_data=$(run_command "$vm_name" "$run_id" "$command")
        ;;
        *)
            exit 1 # cloud provider unknown/not implemented
        ;;
    esac
    
    wait
    local end_time=$(date +%s)
    echo "Finished $cloud VM RunCommand for $vm_name. Ended at $end_time."

    if [[ -n "$run_command_data" ]]; then
        succeeded=$(jq -r '.succeeded' <<< "$run_command_data")
        if [[ "$succeeded" == "true" ]]; then
            output_run_command_data=$run_command_data
            execution_time=$((end_time - start_time))
            execution_succedded="true"
        else
            temporary_run_command_data=$(jq -r '.data' <<< "$run_command_data")
            if [[ -n "$temporary_run_command_data" ]]; then
                output_run_command_data=$run_command_data
            fi
        fi
    fi

    result="{\
        \"operation\": \"run_command\", \
        \"succeeded\": \"$execution_succedded\", \
        \"run_command_data\": $(jq -c -n \
          --argjson run_command_data "$(jq -r '.data' <<< "$output_run_command_data")" \
          '$run_command_data'), \
        \"time\": \"$execution_time\" \
    }"

    mkdir -p $result_dir
    echo $result > "$result_dir/vm-run-command-$cloud-$vm_name-$(date +%s).json"
    echo $result
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
#   - $6: Optional NIC to be used for VM creation/deletion measurement
#   - $7: Optional PIP to be used for VM creation/deletion measurement
#   - $8: The port to use for pinging the VM (e.g. 3389)
#   - $9: The run id
#   - $10: The security group (e.g. my-security-group)
#   - $11: The subnet (e.g. my-subnet)
#   - $12: [optional] The accelerator to use (e.g. count=8,type=nvidia-h100-80gb, default value is empty)
#   - $13: The security type (e.g. TrustedLaunch)
#   - $14: The storage type (e.g. Premium_LRS)
#   - $15: The timeout to wait for a VM creation operation to complete
#   - $16: The result directory where to place the results in JSON format
#   - $17: The test details in JSON format
#   - $18: The tags to use (e.g. "owner=azure_devops,creation_time=2024-03-11T19:12:01Z")
#
# Notes:
#   - the VM ID is returned if no errors occurred
#
# Usage: measure_create_vm <cloud> <vm_name> <vm_size> <vm_os> <region> <nic> <pip> <port> <run_id> <security_group> <subnet> <accelerator> <security_type> <storage_type> <timeout> <result_dir> <test_details> <tags>
measure_create_vm() {
    local cloud=$1
    local vm_name=$2
    local vm_size=$3
    local vm_os=$4
    local region=$5
    local nic=$6
    local pip=$7
    local port=$8
    local run_id=$9
    local security_group=$10
    local subnet=$11
    local accelerator=${12}
    local security_type=${13}
    local storage_type=${14}
    local timeout=${15}
    local result_dir=${16}
    local test_details=${17}
    local tags=${18}

    local creation_succeeded=false
    local creation_time=-1
    local ssh_connection_time=-1
    local vm_id="$vm_name"
    local output_vm_data="{ \"vm_data\": {}}"
    local warning_message=""

    local start_time=$(date +%s)
    case $cloud in
        azure)
            vm_data=$(create_vm "$vm_name" "$vm_size" "$vm_os" "$region" "$run_id" "$nic" "$pip" "$port" "$security_type" "$storage_type" "$timeout" "$tags")
        ;;
        aws)
            vm_data=$(create_ec2 "$vm_name" "$vm_size" "$vm_os" "$region" "$nic" "$pip" "$port" "$subnet" "$timeout" "$tags")
        ;;
        gcp)
            # TODO: this will need to be reviewed once we have the GCP implementation
            vm_data=$(create_vm "$vm_name" "$vm_size" "$vm_os" "$region" "$nic" "$pip" "$accelerator" "$timeout" "$tags")
        ;;
        *)
            exit 1 # cloud provider unknown
        ;;
    esac

    wait

    if [[ -n "$vm_data" ]]; then
        succeeded=$(echo "$vm_data" | jq -r '.succeeded')
        ssh_connection_time=$(echo "$vm_data" | jq -r '.ssh_connection_time')
        command_execution_time=$(echo "$vm_data" | jq -r '.command_execution_time')
        if [[ "$succeeded" == "true" ]]; then
            vm_id=$(echo "$vm_data" | jq -r '.vm_name')
            output_vm_data=$(jq -c -n \
                    --arg vm_data "$(get_vm_info "$vm_id" "$run_id" "$region")" \
                '{vm_data: $vm_data}')
            warning_message=$(echo "$vm_data" | jq -r '.warning_message')
            creation_succeeded=true
        else
            local temporary_vm_data=$(echo "$vm_data" | jq -r '.vm_data')
            if [[ -n "$temporary_vm_data" ]]; then
                output_vm_data=$vm_data
            fi
        fi
    fi

    local result="$test_details, \
        \"vm_id\": \"$vm_id\", \
        \"vm_data\": $(jq -c -n \
          --argjson vm_data "$(echo "$output_vm_data" | jq -r '.vm_data')" \
          '$vm_data'), \
        \"operation\": \"create_vm\", \
        \"ssh_connection_time\": \"$ssh_connection_time\", \
        \"command_execution_time\": \"$command_execution_time\", \
        \"succeeded\": \"$creation_succeeded\", \
        \"warning_message\": \"$warning_message\" \
    }"

    mkdir -p $result_dir
    echo "$result" > "$result_dir/creation-$cloud-$vm_name-$vm_size-$(date +%s).json"

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
#   - $4: The run id
#   - $5: The result directory where to place the results in JSON format
#   - $6: The test details in JSON format
#
# Notes:
#   - the VM ID is returned if no errors occurred
#
# Usage: measure_delete_vm <cloud> <vm_name> <region> <run_id> <result_dir> <test_details>
measure_delete_vm() {
    local cloud=$1
    local vm_name=$2
    local region=$3
    local run_id=$4
    local result_dir=$5
    local test_details=$6
    
    local deletion_succeeded=false
    local deletion_time=-1
    local output_vm_data="{ \"vm_data\": {}}"

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

# Description:
#   This function is used to test the connection to a VM using netcat
#
# Parameters:
#   - $1: The IP of the VM
#   - $2: The port to use
#   - $3: The timeout to wait for the operation to complete
#
# Usage: get_connection_time <ip> <port> <timeout>
get_connection_timestamp() {
    local ip=$1
    local port=$2
    local timeout=$3

    local output=1
    local try=0
    local wait_time=3

    error_file="/tmp/ssh-$ip-$(date +%s).txt"
    set +e
    while [ $output -ne 0 ] && [ $try -lt $timeout ]; do
        netcat -w $wait_time -z $ip $port 2>$error_file
        output=$?
        try=$((try + $wait_time + 1))
        sleep 1
    done
    set -e

    local exit_code=$output
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
#   This function is used to process the results of SSH and CLI commands
#
# Parameters:
#   - $1: The path to the SSH result file
#   - $2: The path to the CLI result file
#   - $3: The path to the error file
#   - $4: The start time of the commands
#   - $5: The instance ID
#
# Returns: The results in JSON format
# Usage: process_results <ssh_file> <cli_file> <error_file> <start_time> <instance_id>
process_results() {
    local ssh_file="$1"
    local cli_file="$2"
    local error_file="$3"
    local start_time="$4"
    local instance_name="$5"

    local succeeded="false"
    local error_message=""
    local warning_message=""
    local cli_success=$(jq -r '.success' "$cli_file")
    local ssh_success=$(jq -r '.success' "$ssh_file")

    if [[ "$ssh_success" == "true" ]]; then
        succeeded="true"
        local ssh_timestamp=$(jq -r '.timestamp' "$ssh_file")
        local ssh_time=$(($ssh_timestamp - $start_time))
    else
        ssh_time=-1
        local ssh_error=$(jq -r '.error' "$ssh_file")
        error_message="$error_message $ssh_error"
    fi

    if [[ "$cli_success" == "true" ]]; then
        succeeded="true"
        local cli_timestamp=$(jq -r '.timestamp' "$cli_file")
        local cli_time=$(($cli_timestamp - $start_time))
    else
        cli_time=-1
        local cli_error=$(jq -r '.error' "$cli_file")
        error_message="$error_message $cli_error"
    fi

    if [[ $succeeded == "true" ]]; then
        warning_message="$(cat "$error_file" | sed -E 's/\\n|\\r|\\t|\\s| /\|/g')"
    fi

    echo $(jq -c -n \
        --arg succeeded "$succeeded" \
        --arg vm_name "$instance_name" \
        --arg ssh_connection_time "$ssh_time" \
        --arg command_execution_time "$cli_time" \
        --arg warning_message "$warning_message" \
    '{succeeded: $succeeded, vm_name: $vm_name, ssh_connection_time: $ssh_connection_time, command_execution_time: $command_execution_time, warning_message: $warning_message}')
}
