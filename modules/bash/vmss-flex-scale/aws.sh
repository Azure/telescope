#!/bin/bash

# Description:
#   This function is used to create an Auto Scaling group instance in AWS.
#
# Parameters:
#   - $1: asg_name: The name of the Auto Scaling group instance (e.g. my-asg)
#   - $2: min_size: Minimum number of instances in the Auto Scaling group (e.g. 1)
#   - $3: max_size: Maximum number of instances in the Auto Scaling group (e.g. 10)
#   - $4: launch_template_name: The name of the launch template to use to launch instances (e.g. my-lt)
#   - $5: region: The region where the Auto Scaling group instance will be created (e.g. us-east-1)
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
    local operation_output = "/tmp/aws-$asg_name-create_asg-output.txt"
    local operation_error = "/tmp/aws-$asg_name-create_asg-error.txt"

    aws autoscaling create-auto-scaling-group \
        --auto-scaling-group-name "$asg_name" \
        --min-size "$min_size" \
        --max-size "$max_size" \
        --launch-template "{\"LaunchTemplateName\":\"$launch_template_name\"}" \
        --region "$region" \
        --tags "$tags" \
        --output json \
        2> "$operation_error" \
        > "$operation_output"

    exit_code=$?

    (
        set -Ee
        function _catch {
            echo $(jq -c -n \
                --arg vmss_name "$asg_name" \
            '{succeeded: "false", vmss_name: $vmss_name, vmss_data: {error: "Unknown error"}}') | sed -E 's/\\n|\\r|\\t|\\s| /\|/g'
        }
        trap _catch ERR

        error=$(cat "$operation_error")

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
#   This function is used to scale (in/out) an Auto Scaling group in AWS.
#
# Parameters:
#   - $1: asg_name: The name of the Auto Scaling group (e.g. my-asg)
#   - $2: desired_capacity: The new VM capacity for the Auto Scaling group (e.g. 20)
#
# Usage: scale_asg <asg_name> <desired_capacity>
scale_asg() {
    local asg_name=$1
    local desired_capacity=$2
    local operation_output = "/tmp/aws-$asg_name-scale_asg-output.txt"
    local operation_error = "/tmp/aws-$asg_name-scale_asg-error.txt"

    aws autoscaling set-desired-capacity \
        --auto-scaling-group-name "$asg_name" \
        --desired-capacity "$desired_capacity" \
        --output json \
        2> "$operation_error" \
        > "$operation_output"

    exit_code=$?
    
    (
        set -Ee
        function _catch {
            echo $(jq -c -n \
                --arg vmss_name "$asg_name" \
            '{succeeded: "false", vmss_name: $vmss_name, vmss_data: {error: "Unknown error"}}') | sed -E 's/\\n|\\r|\\t|\\s| /\|/g'
        }
        trap _catch ERR

        error=$(cat "$operation_error")

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
#   This function waits for all scaling activities to complete for a given Auto Scaling group.
#
# Parameters:
#   - $1: asg_name: The name of the Auto Scaling group
#
# Usage: wait_for_scaling_activities <asg_name>
wait_for_scaling_activities() {
    local asg_name=$1

    >&2 echo "Waiting for scaling activities to complete for ASG: $asg_name"

    while true; do
        local activities=$(aws autoscaling describe-scaling-activities --auto-scaling-group-name "$asg_name" --query "Activities[?StatusCode=='InProgress']" --output json)
        if [ "$activities" == "[]" ]; then
            >&2 echo "No scaling activities in progress for ASG: $asg_name"
            break
        fi
        >&2 echo "Scaling activities in progress for ASG: $asg_name. Waiting..."
        sleep 1
    done
}

# Description:
#   This function waits for the Auto Scaling group to have the desired capacity.
#
# Parameters:
#   - $1: asg_name: The name of the Auto Scaling group
#   - $2: desired_capacity: The desired capacity of the Auto Scaling group
#
# Usage: wait_for_desired_capacity <asg_name> <desired_capacity>
wait_for_desired_capacity() {
    local asg_name=$1
    local desired_capacity=$2

    >&2 echo "Waiting for Auto Scaling group $asg_name to reach desired capacity of $desired_capacity"

    while true; do
        local in_service_count=$(aws autoscaling describe-auto-scaling-groups --auto-scaling-group-names "$asg_name" --query "AutoScalingGroups[0].Instances[?LifecycleState=='InService'].InstanceId" --output json | jq length)
        if [ "$in_service_count" -eq "$desired_capacity" ]; then
            >&2 echo "Auto Scaling group $asg_name has reached the desired capacity of $desired_capacity"
            break
        fi
        >&2 echo "Current in-service instances: $in_service_count. Waiting..."
        sleep 1
    done
}

# Description:
#   This function updates the minimum size and desired capacity of an Auto Scaling group.
#
# Parameters:
#   - $1: asg_name: The name of the Auto Scaling group
#   - $2: min_size: The new minimum size of the Auto Scaling group
#   - $3: desired_capacity: The new desired capacity of the Auto Scaling group
#
# Usage: update_autoscaling_group <asg_name> <min_size> <desired_capacity>
update_autoscaling_group() {
    local asg_name=$1
    local min_size=$2
    local desired_capacity=$3

    >&2 echo "Updating Auto Scaling group $asg_name to min size $min_size and desired capacity $desired_capacity..."

    aws autoscaling update-auto-scaling-group \
        --auto-scaling-group-name "$asg_name" \
        --min-size "$min_size" \
        --desired-capacity "$desired_capacity"

    if [ $? -eq 0 ]; then
        >&2 echo "Auto Scaling group $asg_name updated successfully."
    else
        >&2 echo "Failed to update Auto Scaling group $asg_name."
    fi
}

# Description:
#   This function is used to delete an Auto Scaling group in AWS.
#
# Parameters:
#   - $1: asg_name: The name of the Auto Scaling group (e.g. my-asg)
#
# Usage: delete_asg <asg_name>
delete_asg() {
    local asg_name=$1
    local operation_output = "/tmp/aws-$asg_name-delete_asg-output.txt"
    local operation_error = "/tmp/aws-$asg_name-delete_asg-error.txt"

    aws autoscaling delete-auto-scaling-group \
    --auto-scaling-group-name "$asg_name" \
    --output json \
    2> "$operation_error" \
    > "$operation_output"

    exit_code=$?
    
    (
        set -Ee
        function _catch {
            echo $(jq -c -n \
                --arg vmss_name "$asg_name" \
            '{succeeded: "false", vmss_name: $vmss_name, vmss_data: {error: "Unknown error"}}') | sed -E 's/\\n|\\r|\\t|\\s| /\|/g'
        }
        trap _catch ERR

        error=$(cat "$operation_error")

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
#   This script waits until there are no more Auto Scaling groups with a given name.
#
# Parameters:
#   - $1: asg_name: The name of the Auto Scaling group
#
# Usage: wait_until_no_autoscaling_groups <asg_name>
wait_until_no_autoscaling_groups() {
    local asg_name=$1

    >&2 echo "Waiting for Auto Scaling group $asg_name to be deleted..."

    while true; do
        local group_count=$(aws autoscaling describe-auto-scaling-groups --auto-scaling-group-names "$asg_name" --query "AutoScalingGroups" --output json 2>/dev/null | jq length)

        if [ "$group_count" -eq 0 ]; then
            >&2 echo "No Auto Scaling groups found with the name: $asg_name"
            break
        else
            >&2 echo "Auto Scaling group with the name $asg_name still exists. Waiting..."
        fi
        sleep 1
    done
}

# Description:
#   This function is used to create a Launch Template in AWS.
#
# Parameters:
#   - $1: lt_name: The name of the launch template (e.g. my-lt)
#   - $2: vm_size: The size of the VM used in the Auto Scaling group (e.g. m5i.large)
#   - $3: vm_os: The OS identifier the VM will use (e.g. ubuntu:22.04:x86_64)
#   - $4: security_group_id: The security group id to use for the VM (e.g. sg-1234567890)
#   - $5: subnet_id: The subnet id to use for the VM (e.g. subnet-1234567890)
#   - $6: region: The region where the Launch Template will be created (e.g. us-east-1)
#
# Usage: create_lt <lt_name> <vm_size> <vm_os> <security_group_id> <subnet_id> <region>
create_lt() {
    local lt_name=$1
    local vm_size=$2
    local vm_os=$3
    local security_group_id=$4
    local subnet_id=$5
    local region=$6

    launch_template_id=$(aws ec2 create-launch-template --launch-template-name "$lt_name"  \
                            --launch-template-data "{\"ImageId\":\"$vm_os\",\"InstanceType\":\"$vm_size\", \"NetworkInterfaces\":[{\"DeviceIndex\":0, \"Groups\":[\"$security_group_id\"], \"SubnetId\":\"$subnet_id\"}]}" \
                            --region "$region" \
                            --output text \
                            --query 'LaunchTemplate.LaunchTemplateId')

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

    if aws ec2 delete-launch-template --launch-template-name "$lt_name"; then
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