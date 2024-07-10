#!/bin/bash

# Description:
#   This function gets the ids of the running VM instances (called name for Azure compatibility) by run id.

# Parameters:
#  - $1: run_id: the ID of the test run (e.g. c23f34-vf34g34g-3f34gf3gf4-fd43rf3f43)
# 
# Returns: The ids of the VM instances
# Usage: get_vm_instances_name_by_run_id <run_id>
get_vm_instances_name_by_run_id() {
    local run_id=$1

    echo "$(aws ec2 describe-instances \
        --filters Name=tag:run_id,Values=$run_id Name=instance-state-name,Values=running \
        --query "Reservations[].Instances[].InstanceId" \
        --output text)"
}

#   This function is used to retrieve the information of an EC2 instance in AWS.
#
# Parameters:
#   - $1: The ID of the EC2 instance (e.g. i-0d5d9d301c853a04a)
#
# Usage: get_vm_info <instance_id>
get_vm_info() {
    local instance_id=$1
    
    aws ec2 describe-instances --instance-ids "$instance_id" --output json
}

# Description:
#   This function is used to create an EC2 instance in AWS.
#
# Parameters:
#   - $1: The name of the EC2 instance (e.g. my-vm)
#   - $2: The size of the EC2 instance (e.g. t2.micro)
#   - $3: The OS the EC2 instance will use (e.g. ami-0d5d9d301c853a04a)
#   - $4: The region where the EC2 instance will be created (e.g. us-east-1)
#   - $5: [optional] The id of the NIC the EC2 instance uses (e.g. eni-0d5d9d301c853a04a)
#   - $6: The Public IP associated with the EC2 instance (e.g. 8.8.8.8)
#   - $7: [optional] The port to use (e.g. 22)
#   - $8: [optional] The id of the subnet the EC2 instance uses (e.g. subnet-0d5d9d301c853a04a)
#   - $9: [optional] The timeout to use (e.g. 300, default value is 300)
#   - $10: [optional] The tags to use (e.g. "ResourceType=instance,Tags=[{Key=owner,Value=azure_devops},{Key=creation_time,Value=2024-03-11T19:12:01Z}]", default value is "ResourceType=instance,Tags=[{Key=owner,Value=azure_devops}]")
#
# Notes:
#   - this commands waits for the EC2 instance's state to be running before returning the instance id
#
# Usage: create_ec2 <instance_name> <instance_size> <instance_os> <region> [nic] <pip> [port] [subnet] [tag_specifications]
create_ec2() {
    local instance_name=$1
    local instance_size=$2
    local instance_os=$3
    local region=$4
    local nic="${5:-""}"
    local pip=$6
    local port="${7:-"22"}"
    local subnet="${8:-""}"
    local timeout="${9:-"300"}"
    local tag_specifications="${10:-"ResourceType=instance,Tags=[{Key=owner,Value=azure_devops}]"}"

    local ssh_file="/tmp/ssh-$instance_name-$(date +%s)"
    local cli_file="/tmp/cli-$instance_name-$(date +%s)"
    local error_file="/tmp/aws-$instance_name-create_ec2-error.txt"
    local output_file="/tmp/aws-$instance_name-create_ec2-output.txt"

    local start_time=$(date +%s)

    if [[ -n "$nic" ]]; then
        aws ec2 run-instances --region "$region" --image-id "$instance_os" --instance-type "$instance_size" --network-interfaces "[{\"NetworkInterfaceId\": \"$nic\", \"DeviceIndex\": 0}]" --tag-specifications "$tag_specifications" --output json 2> "$error_file" > "$output_file"
    else
        aws ec2 run-instances --region "$region" --image-id "$instance_os" --instance-type "$instance_size" --subnet-id "$subnet" --tag-specifications "$tag_specifications" --output json 2> "$error_file" > "$output_file"
    fi

    local exit_code=$?

    local instance_data="$(cat $output_file)"
    local instance_id=$(echo "$instance_data" | jq -r '.Instances[0].InstanceId')

    if [[ $exit_code -eq 0 ]]; then
        (get_connection_timestamp "$pip" "$port" "$timeout" > "$ssh_file") &
        (get_running_state_timestamp "$instance_id" "$timeout" > "$cli_file") &
        wait
    fi

    echo "$(create_vm_output "$instance_name" "$instance_id" "$instance_data" "$start_time" "$ssh_file" "$cli_file" "$error_file" "$exit_code")"
}

# Description:
#   This function is used to delete an EC2 instance in AWS.
#
# Parameters:
#   - $1: The id of the EC2 instance (e.g. i-0d5d9d301c853a04a)
#   - $2: The region where the EC2 instance was created (e.g. us-east-1)
#
# Notes:
#   - this commands waits for the EC2 instance's state to be terminated before returning the instance id
#
# Usage: delete_ec2 <instance_id> <region>
delete_ec2() {
    local instance_id=$1
    local region=$2

    aws ec2 terminate-instances --region "$region" --instance-ids "$instance_id" --output json 2> "/tmp/aws-$instance_id-delete_ec2-error.txt" > "/tmp/aws-$instance_id-delete_ec2-output.txt"

    exit_code=$?
    
    (
        set -Ee
        function _catch {
            echo $(jq -c -n \
                --arg vm_name "$instance_id" \
            '{succeeded: "false", vm_name: $vm_name, vm_data: {error: "Unknown error"}}') | sed -E 's/\\n|\\r|\\t|\\s| /\|/g'
        }
        trap _catch ERR

        instance_data=$(cat /tmp/aws-$instance_id-delete_ec2-output.txt)
        error=$(cat /tmp/aws-$instance_id-delete_ec2-error.txt)

        if [[ $exit_code -eq 0 ]]; then
            instance_id=$(echo "$instance_data" | jq -r '.TerminatingInstances[0].InstanceId')

            if [[ -n "$instance_id" ]] && [[ "$instance_id" != "null" ]]; then
                if aws ec2 wait instance-terminated --region "$region" --instance-ids "$instance_id"; then
                    echo $(jq -c -n \
                        --arg vm_name "$instance_id" \
                        --argjson vm_data "$(echo "$instance_data" | jq -r)" \
                    '{succeeded: "true", vm_name: $vm_name, vm_data: $vm_data}') | sed -E 's/\\n|\\r|\\t|\\s| /\|/g'
                fi
            else
                echo $(jq -c -n \
                    --arg vm_name "$instance_id" \
                    --arg vm_data "$instance_data" \
                '{succeeded: "false", vm_name: $vm_name, vm_data: {error: $vm_data}}') | sed -E 's/\\n|\\r|\\t|\\s| /\|/g'
            fi
        else
            echo $(jq -c -n \
                --arg vm_name "$instance_id" \
                --arg vm_data "$error" \
            '{succeeded: "false", vm_name: $vm_name, vm_data: {error: $vm_data}}') | sed -E 's/\\n|\\r|\\t|\\s| /\|/g'
        fi
    )
}

# Description:
#   This function is used to create a PIP in AWS.
#
# Parameters:
#   - $1: The region where the PIP is located (e.g. us-east-1)
#   - $2: [optional] The tags to use (e.g. "ResourceType=elastic-ip,Tags=[{Key=owner,Value=azure_devops}]", default value is "ResourceType=elastic-ip,Tags=[{Key=owner,Value=azure_devops}]")
#
# Notes:
#   - the PIP id is returned if no errors occurred
#
# Usage: create_pip <region> [tag_specifications]
create_pip() {
    local region=$1
    local tag_specifications="${2:-"ResourceType=elastic-ip,Tags=[{Key=owner,Value=azure_devops}]"}"

    pip=$(aws ec2 allocate-address --domain "vpc" --region "$region" --tag-specifications "$tag_specifications" --output "json")

    if [[ -n "$pip" ]]; then
        echo "$pip"
    fi
}

# Description:
#   This function is used to create a NIC in AWS.
#
# Parameters:
#   - $1: The name of the NIC (e.g. nic_my-vm)
#   - $2: The id of the subnet the network interface uses (e.g. subnet-0d5d9d301c853a04a)
#   - $3: The id of the security group to add the network interface to (e.g. security-group-0d5d9d301c853a04a)
#   - $4: The id of the public IP address to associate with the network interface (e.g. eipalloc-0d5d9d301c853a04a)
#   - $5: [optional] The tags to use (e.g. "ResourceType=network-interface,Tags=[{Key=owner,Value=azure_devops},{Key=creation_time,Value=2024-03-11T19:12:01Z}]", default value is "ResourceType=instance,Tags=[{Key=owner,Value=azure_devops}]")
#
# Notes:
#   - the NIC id is returned if no errors occurred
#
# Usage: create_nic <nic_name> <subnet> <security_group> <pip_id> [tag_specifications]
create_nic() {
    local nic_name=$1
    local subnet=$2
    local security_group=$3
    local pip_id=$4
    local tag_specifications="${5:-"ResourceType=network-interface,Tags=[{Key=owner,Value=azure_devops}]"}"

    nic_id=$(aws ec2 create-network-interface --description "$nic_name" --subnet-id "$subnet" --groups "$security_group" --tag-specifications "$tag_specifications" --output text --query 'NetworkInterface.NetworkInterfaceId')

    if [[ -n "$nic_id" ]]; then
        associate_output=$(aws ec2 associate-address --network-interface-id "$nic_id" --allocation-id "$pip_id")

        echo "$nic_id"
    fi
}

# Description:
#   This function is used to delete a PIP in AWS.
#
# Parameters:
#   - $1: The id of the PIP (e.g. eipalloc-0d5d9d301c853a04a)
#
# Notes:
#   - the PIP id is returned if no errors occurred
#
# Usage: delete_pip <pip_id>
delete_pip() {
    local pip_id=$1

    if aws ec2 release-address --allocation-id "$pip_id"; then
        echo "$pip_id"
    fi
}

# Description:
#   This function is used to delete a NIC in AWS.
#
# Parameters:
#   - $1: The id of the NIC (e.g. eni-0d5d9d301c853a04a)
#
# Notes:
#   - the NIC id is returned if no errors occurred
#
# Usage: delete_nic <nic_id>
delete_nic() {
    local nic_id=$1

    if aws ec2 delete-network-interface --network-interface-id "$nic_id"; then
        echo "$nic_id"
    fi
}

# Description:
#   This function is used to retrieve a security group by filters
#
# Parameters:
#   - $1: The region where the security group is located (e.g. us-east-1)
#   - $2: The filters to use (e.g. "Name=tag:name,Values=create-delete-vm-sg")
#
# Usage: get_security_group_by_filters <region> <filters>
get_security_group_by_filters() {
    local region=$1
    local filters=$2

    aws ec2 describe-security-groups --region "$region" --filters $filters --output text --query 'SecurityGroups[0].GroupId'
}

# Description:
#   This function is used to retrieve a subnet by filters
#
# Parameters:
#   - $1: The region where the subnet is located (e.g. us-east-1)
#   - $2: The filters to use (e.g. "Name=tag:name,Values=create-delete-vm-subnet")
#
# Usage: get_subnet_by_filters <region> <filters>
get_subnet_by_filters() {
    local region=$1
    local filters=$2

    aws ec2 describe-subnets --region "$region" --filters $filters --output text --query 'Subnets[0].SubnetId'
}

# Description:
#   This function is used to retrieve a network interface by filters
#
# Parameters:
#   - $1: The region where the network interface is located (e.g. us-east-1)
#   - $2: The filters to use (e.g. "Name=tag:name,Values=create-delete-vm-network-interface")
#
# Usage: get_nic_by_filters <region> <filters>
get_nic_by_filters() {
    local region=$1
    local filters=$2

    aws ec2 describe-network-interfaces --region "$region" --filters $filters --output text --query 'NetworkInterfaces[0].NetworkInterfaceId'
}

# Description:
#   This function is used to retrieve the latest image id for a given OS type, version, and architecture
#
# Parameters:
#   - $1: The region where the image is located (e.g. us-east-1)
#   - $2: The OS type (e.g. ubuntu)
#   - $3: The OS version (e.g. 22.04)
#   - $4: The architecture (e.g. x86_64)
#
# Notes:
#   - the image id is returned if no errors occurred
#
# Usage: get_latest_image <region> <os_type> <os_version> <architecture>
function get_latest_image {
    local region=$1
    local os_type=$2
    local os_version=$3
    local architecture=$4

    local name_pattern

    if [ "$os_type" = "windows" ]; then
        name_pattern="$os_version*"
    elif [ "$os_type" = "ubuntu" ]; then
        name_pattern="ubuntu/images/hvm-ssd/ubuntu-*-$os_version-*-server-*"
    else
        echo "Unsupported OS type: $os_type"
        return 1
    fi

    local ami_id=$(aws ec2 describe-images --region $region \
        --owners "amazon" \
        --filters "Name=name,Values=$name_pattern" \
                    "Name=architecture,Values=$architecture" \
                    "Name=state,Values=available" \
        --query "reverse(sort_by(Images, &CreationDate))[:1].ImageId" \
        --output text)

    echo "$ami_id"
}

# Description:
#   This function is used to run custom script commands on EC2
#
# Parameters:
#   - $1: The instance id (e.g. i-9014ujtn1509)
#   - $2: The region where the image is located (e.g. us-east-1)
#   - $3: Commands to execute (e.g. '{"commands":["echo \"Hello, World!\""]}')
#
# Notes:
#   - a json with the result is returned
#
# Usage: install_ec2_extension <instance_id> <region>
install_ec2_extension() {
    local instance_id=$1
    local region=$2
    local command=${3:-'{"commands":["echo \"Hello, World!\""]}'}

    aws ssm send-command \
        --instance-ids "$instance_id" \
        --document-name "AWS-RunShellScript" \
        --comment "Executing custom script" \
        --parameters "$command" \
        --region "$region" \
        --output json \
        2> /tmp/$instance_id-install-extension-error.txt \
        > /tmp/$instance_id-install-extension-output.txt

    exit_code=$?

    (
        extension_data=$(cat /tmp/$instance_id-install-extension-output.txt)
        error=$(cat /tmp/$instance_id-install-extension-error.txt)

        if [[ $exit_code -eq 0 ]]; then
            command_id="$(echo "$extension_data" | jq -r '.Command.CommandId')"
            aws ssm wait command-executed --command-id "$command_id" --instance-id "$instance_id" --region "$region"
            command_status="$(aws ssm list-command-invocations --command-id "$command_id" \
                --details --region "$region" \
                --output text \
                --query 'CommandInvocations[*].{Status:Status}')"

            if [ "$command_status" = "Success" ]; then
                succeeded=true
            else
                succeeded=false
            fi

            echo $(jq -c -n \
                --arg succeeded "$succeeded" \
                --argjson extension_data "$extension_data" \
            '{succeeded: $succeeded, data: $extension_data}')
        else
            echo $(jq -c -n \
                --arg error "$error" \
                '{succeeded: "false", data: {error: $error}}')
        fi
    )
}

# Description:
#   This function waits for an EC2 instance to reach the running state and returns the timestamp when it does.

# Parameters:
#   - $1: The ID of the EC2 instance (e.g. i-0d5d9d301c853a04a)
#   - $2: Number of seconds after which the command times out

# Usage: get_running_state_timestamp <instance_id> <timeout>
get_running_state_timestamp() {
    local instance_id=$1
    local timeout=$2

    local error_file="/tmp/aws-cli-"$(date +%s)"-error.txt"
    timeout $timeout aws ec2 wait instance-running --instance-ids "$instance_id" 2> "$error_file"
    local exit_code=$?

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
#   This function is used to execute the code for creating VM output.

# Parameters:
#   - $1: The instance name
#   - $2: The instance ID
#   - $3: The instance data
#   - $4: The start time of the instance creation
#   - $5: The path to the ssh file
#   - $6: The path to the cli file
#   - $7: The path to the error file
#   - $8: The exit code of the create command

# Usage: create_vm_output <instance_name> <instance_id> <instance_data> <start_time> <ssh_file> <cli_file> <error_file> <command_exit_code>
create_vm_output() {
    local instance_name="$1"
    local instance_id="$2"
    local instance_data="$3"
    local start_time="$4"
    local ssh_file="$5"
    local cli_file="$6"
    local error_file="$7"
    local command_exit_code="$8"

    set -Ee
    function _catch {
        echo $(jq -c -n \
            --arg vm_name "$instance_name" \
        '{succeeded: "false", vm_name: $vm_name, vm_data: {error: "Unknown error"}}') | sed -E 's/\\n|\\r|\\t|\\s| /\|/g'
    }
    trap _catch ERR

    local error=$(cat "$error_file")

    if [[ -n "$error" && "$command_exit_code" -ne 0 ]]; then
        echo $(jq -c -n \
    --arg vm_name "$instance_name" \
    --arg vm_data "$error" \
'{succeeded: "false", vm_name: $vm_name, vm_data: {error: $vm_data}}') | sed -E 's/\\n|\\r|\\t|\\s| /\|/g'
    elif [[ "$command_exit_code" -ne 0 ]]; then
        echo $(jq -c -n \
            --arg vm_name "$vm_name" \
            --arg command_exit_code "$command_exit_code" \
        '{succeeded: "false", vm_name: $vm_name, vm_data: {error: "Command exited with code $command_exit_code. No error available."}}') | sed -E 's/\\n|\\r|\\t|\\s| /\|/g'
    else
        if [[ -n "$instance_id" ]] && [[ "$instance_id" != "null" ]]; then
            echo "$(process_results "$ssh_file" "$cli_file" "$error_file" "$start_time" "$instance_id" )"
        else
            echo $(jq -c -n \
                --arg vm_name "$instance_id" \
                --arg vm_data "$instance_data" \
            '{succeeded: "false", vm_name: $vm_name, vm_data: {error: $vm_data}}') | sed -E 's/\\n|\\r|\\t|\\s| /\|/g'
        fi
    fi
}
