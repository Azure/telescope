#!/bin/bash

# Description:
#   This function is used to create an ASG instance in AWS.
#
# Parameters:
#   - $1: asg_name: The name of the ASG instance (e.g. my-asg)
#   - $2: min_size: Minimum number of instances in the ASG (e.g. 1)
#   - $3: max_size: Maximum number of instances in the ASG (e.g. 10)
#   - $4: launch_template_name: The name of the launch template to use to launch instances (e.g. my-lt)
#   - $5: region: The region where the ASG instance will be created (e.g. us-east-1)
#   - $6: tags: [optional] The tags to use (e.g. "ResourceType=instance,Tags=[{Key=owner,Value=azure_devops},{Key=creation_time,Value=2024-03-11T19:12:01Z}]", default value is "ResourceType=instance,Tags=[{Key=owner,Value=azure_devops}]")
#
# Usage: create_asg <asg_name> <min_size> <max_size> <launch_template_name> <region> [tags]
create_asg() {
    local asg_name=$1
    local min_size=$2
    local max_size=$3
    local launch_template_name=$4
    local region=$5
    local tags="${6:-"ResourceType=instance,Tags=[{Key=owner,Value=azure_devops}]"}"

    aws autoscaling create-auto-scaling-group \
        --auto-scaling-group-name $asg_name \
        --min-size $min_size \
        --max-size $max_size \
        --launch-template "{\"LaunchTemplateName\":\"$launch_template_name\"}" \
        --availability-zones $region \
        --tags $tags \
        --output json \
        2> "/tmp/aws-$asg_name-create_asg-error.txt" \
        > "/tmp/aws-$asg_name-create_asg-output.txt"

    exit_code=$?

    (
        set -Ee
        function _catch {
            echo $(jq -c -n \
                --arg vmss_name "$asg_name" \
            '{succeeded: "false", vmss_name: $vmss_name, vmss_data: {error: "Unknown error"}}') | sed -E 's/\\n|\\r|\\t|\\s| /\|/g'
        }
        trap _catch ERR

        error=$(cat "/tmp/aws-$asg_name-create_asg-error.txt")

        if [[ $exit_code -eq 0 ]]; then
            echo $(jq -c -n \
                --arg vmss_name "$asg_name" \
            '{succeeded: "true", vmss_name: $vmss_name}') | sed -E 's/\\n|\\r|\\t|\\s| /\|/g'
        else
            if [[ -n "$error" ]] && [[ "${error:0:8}" == "ERROR: {" ]]; then
                echo $(jq -c -n \
                    --arg vmss_name "$asg_name" \
                '{succeeded: "false", vmss_name: $vmss_name, vmss_data: {error: $vmss_data}}') | sed -E 's/\\n|\\r|\\t|\\s| /\|/g'
            else
                echo $(jq -c -n \
                    --arg vmss_name "$asg_name" \
                    --arg vmss_data "$error" \
                '{succeeded: "false", vmss_name: $vmss_name, vmss_data: {error: $vmss_data}}') | sed -E 's/\\n|\\r|\\t|\\s| /\|/g'
            fi
        fi
    )
}

# Description:
#   This function is used to scale (in/out) an ASG in AWS.
#
# Parameters:
#   - $1: asg_name: The name of the ASG (e.g. my-asg)
#   - $2: desired_capacity: The new VM capacity for the ASG (e.g. 20)
#
# Usage: scale_asg <asg_name> <desired_capacity>
scale_asg() {
    local asg_name=$1
    local desired_capacity=$2

    aws autoscaling set-desired-capacity \
        --auto-scaling-group-name $asg_name \
        --desired-capacity $desired_capacity \
        --output json \
        2> "/tmp/aws-$asg_name-scale_asg-error.txt" \
        > "/tmp/aws-$asg_name-scale_asg-output.txt"

    exit_code=$?
    
    (
        set -Ee
        function _catch {
            echo $(jq -c -n \
                --arg vmss_name "$asg_name" \
            '{succeeded: "false", vmss_name: $vmss_name, vmss_data: {error: "Unknown error"}}') | sed -E 's/\\n|\\r|\\t|\\s| /\|/g'
        }
        trap _catch ERR

        error=$(cat "/tmp/aws-$asg_name-scale_asg-error.txt")

        if [[ $exit_code -eq 0 ]]; then
            echo $(jq -c -n \
                --arg vmss_name "$asg_name" \
            '{succeeded: "true", vmss_name: $vmss_name}') | sed -E 's/\\n|\\r|\\t|\\s| /\|/g'
        else
            if [[ -n "$error" ]] && [[ "${error:0:8}" == "ERROR: {" ]]; then
                echo $(jq -c -n \
                    --arg vmss_name "$asg_name" \
                '{succeeded: "false", vmss_name: $vmss_name, vmss_data: {error: $vmss_data}}') | sed -E 's/\\n|\\r|\\t|\\s| /\|/g'
            else
                echo $(jq -c -n \
                    --arg vmss_name "$asg_name" \
                    --arg vmss_data "$error" \
                '{succeeded: "false", vmss_name: $vmss_name, vmss_data: {error: $vmss_data}}') | sed -E 's/\\n|\\r|\\t|\\s| /\|/g'
            fi
        fi
    )
}

# Description:
#   This function is used to delete an ASG in AWS.
#
# Parameters:
#   - $1: asg_name: The name of the ASG (e.g. my-asg)
#
# Usage: delete_asg <asg_name>
delete_asg() {
    local asg_name=$1

    aws autoscaling delete-auto-scaling-group \
    --auto-scaling-group-name $asg_name \
    --output json \
    2> "/tmp/aws-$asg_name-delete_asg-error.txt" \
    > "/tmp/aws-$asg_name-delete_asg-output.txt"

    exit_code=$?
    
    (
        set -Ee
        function _catch {
            echo $(jq -c -n \
                --arg vmss_name "$asg_name" \
            '{succeeded: "false", vmss_name: $vmss_name, vmss_data: {error: "Unknown error"}}') | sed -E 's/\\n|\\r|\\t|\\s| /\|/g'
        }
        trap _catch ERR

        error=$(cat "/tmp/aws-$asg_name-delete_asg-error.txt")

        if [[ $exit_code -eq 0 ]]; then
            echo $(jq -c -n \
                --arg vmss_name "$asg_name" \
            '{succeeded: "true", vmss_name: $vmss_name}') | sed -E 's/\\n|\\r|\\t|\\s| /\|/g'
        else
            if [[ -n "$error" ]] && [[ "${error:0:8}" == "ERROR: {" ]]; then
                echo $(jq -c -n \
                    --arg vmss_name "$asg_name" \
                '{succeeded: "false", vmss_name: $vmss_name, vmss_data: {error: $vmss_data}}') | sed -E 's/\\n|\\r|\\t|\\s| /\|/g'
            else
                echo $(jq -c -n \
                    --arg vmss_name "$asg_name" \
                    --arg vmss_data "$error" \
                '{succeeded: "false", vmss_name: $vmss_name, vmss_data: {error: $vmss_data}}') | sed -E 's/\\n|\\r|\\t|\\s| /\|/g'
            fi
        fi
    )
}

# Description:
#   This function is used to create a Launch Template in AWS.
#
# Parameters:
#   - $1: lt_name: The name of the launch template (e.g. my-lt)
#   - $2: vm_size: The size of the VM used in the ASG (e.g. m5i.large)
#   - $3: vm_os: The OS identifier the VM will use (e.g. ubuntu:22.04:x86_64)
#   - $4: security_group: The security group to use for the VM (e.g. sg-1234567890)
#
# Usage: create_lt <lt_name> <vm_size> <vm_os> <security_group>
create_lt() {
    local lt_name=$1
    local vm_size=$2
    local vm_os=$3
    local security_group=$4

    launch_template_id=$(aws ec2 create-launch-template --launch-template-name $lt_name  \
                            --launch-template-data "{\"ImageId\":\"$vm_os\",\"InstanceType\":\"$vm_size\", \"SecurityGroups\":[\"$security_group\"]}" \
                            --output text --query 'LaunchTemplate.LaunchTemplateId')

    if [[ -n "$launch_template_id" ]]; then
        echo "$launch_template_id"
    fi
}

# Description:
#   This function is used to delete a Launch Template in AWS.
#
# Parameters:
#   - $1: lt_name: The name of the launch template (e.g. my-lt)
#
# Usage: delete_lt <lt_name>
delete_lt() {
    local lt_name=$1

    if aws ec2 delete-launch-template --launch-template-name $lt_name; then
        echo "$lt_name"
    fi
}

# Description:
#   This function is used to retrieve the latest image id for a given OS type, version, and architecture
#
# Parameters:
#   - $1: region: The region where the image is located (e.g. us-east-1)
#   - $2: os_type: The OS type (e.g. ubuntu)
#   - $3: os_version: The OS version (e.g. 22.04)
#   - $4: architecture: The architecture (e.g. x86_64)
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