#!/bin/bash

# Description:
#   This function is used to create an EC2 instance in AWS.
#
# Parameters:
#   - $1: The name of the EC2 instance (e.g. my-vm)
#   - $2: The size of the EC2 instance (e.g. t2.micro)
#   - $3: The OS the EC2 instance will use (e.g. ami-0d5d9d301c853a04a)
#   - $4: The region where the EC2 instance will be created (e.g. us-east-1)
#   - $5: [optional] The id of the security group to add the EC2 instance to (e.g. security-group-0d5d9d301c853a04a)
#   - $6: [optional] The id of the NIC the EC2 instance uses (e.g. eni-0d5d9d301c853a04a)
#   - $7: [optional] The id of the subnet the EC2 instance uses (e.g. subnet-0d5d9d301c853a04a)
#   - $8: [optional] The tags to use (e.g. "ResourceType=instance,Tags=[{Key=owner,Value=azure_devops},{Key=creation_time,Value=2024-03-11T19:12:01Z}]", default value is "ResourceType=instance,Tags=[{Key=owner,Value=azure_devops}]")
#
# Notes:
#   - this commands waits for the EC2 instance's state to be running before returning the instance id
#
# Usage: create_ec2 <name> <size> <os> <region> <subnet> [tag_specifications]
create_asg() {
    local asg_name=$1
    local min_size=$2
    local max_size=$3
    local desired_capacity=$4
    local launch_template_name=$5
    local region=$6
    local tag_specifications="${7:-"ResourceType=instance,Tags=[{Key=owner,Value=azure_devops}]"}"

    aws autoscaling create-auto-scaling-group --auto-scaling-group-name $asg_name --min-size $min_size --max-size $max_size --desired-capacity $desired_capacity --launch-template "{\"LaunchTemplateName\":\"$launch_template_name\"}" --availability-zones $region --tag-specifications "$tag_specifications" --output json 2> /tmp/aws-$asg_name-create_asg-error.txt > /tmp/aws-$asg_name-create_asg-output.txt

    exit_code=$?

    (
        set -Ee
        function _catch {
            echo $(jq -c -n \
                --arg asg_name "$asg_name" \
            '{succeeded: "false", asg_name: $asg_name, asg_data: {error: "Unknown error"}}') | sed -E 's/\\n|\\r|\\t|\\s| /\|/g'
        }
        trap _catch ERR

        instance_data=$(cat /tmp/aws-$asg_name-create_asg-output.txt)
        error=$(cat /tmp/aws-$asg_name-create_asg-error.txt)

        if [[ $exit_code -eq 0 ]]; then
            instance_id=$(echo "$instance_data" | jq -r '.Instances[0].InstanceId')

            if [[ -n "$instance_id" ]] && [[ "$instance_id" != "null" ]]; then
                if aws ec2 wait instance-running --region "$region" --instance-ids "$instance_id"; then
                    echo $(jq -c -n \
                        --arg vm_name "$instance_id" \
                        --argjson vm_data "$instance_data" \
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
                --arg vm_name "$instance_name" \
                --arg vm_data "$error" \
            '{succeeded: "false", vm_name: $vm_name, vm_data: {error: $vm_data}}') | sed -E 's/\\n|\\r|\\t|\\s| /\|/g'
        fi
    )
}

scale_asg() {
    local asg_name=$1
    local desired_capacity=$2

    aws autoscaling set-desired-capacity --auto-scaling-group-name $asg_name --desired-capacity $desired_capacity --output json 2> /tmp/aws-$asg_name-scale_asg-error.txt > /tmp/aws-$asg_name-scale_asg-output.txt
}

delete_asg() {
    local asg_name=$1

    aws autoscaling delete-auto-scaling-group --auto-scaling-group-name $asg_name --output json 2> /tmp/aws-$asg_name-delete_asg-error.txt > /tmp/aws-$asg_name-delete_asg-output.txt

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

create_lt() {
    local lt_name=$1
    local vm_size=$2
    local vm_os=$3

    launch_template_id=$(aws ec2 create-launch-template --launch-template-name $lt_name --launch-template-data "{\"ImageId\":\"$vm_os\",\"InstanceType\":\"$vm_size\"}" --output text --query 'LaunchTemplate.LaunchTemplateId')

    if [[ -n "$launch_template_id" ]]; then
        echo "$launch_template_id"
    fi
}

delete_lt() {
	local lt_name=$1

	if aws ec2 delete-launch-template --launch-template-name $lt_name; then
        echo "$lt_name"
	fi

}