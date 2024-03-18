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
#   - $6: [optional] The id of the subnet the EC2 instance uses (e.g. subnet-0d5d9d301c853a04a)
#   - $7: [optional] The tags to use (e.g. "ResourceType=instance,Tags=[{Key=owner,Value=azure_devops},{Key=creation_time,Value=2024-03-11T19:12:01Z}]", default value is "ResourceType=instance,Tags=[{Key=owner,Value=azure_devops}]")
#
# Notes:
#   - this commands waits for the EC2 instance's state to be running before returning the instance id
#   - the instance id is returned if no errors occurred
#   - you cannot create an EC2 instance by providing both security group and subnet id - if the method is called with both, the security group will take precedence
#
# Usage: create_ec2 <name> <size> <os> <region> <security_group> <subnet> [tag_specifications]
create_ec2() {
    local instance_name=$1
    local instance_size=$2
    local instance_os=$3
    local region=$4
    local security_group="${5:-""}"
    local subnet="${6:-""}"
    local tag_specifications="${7:-"ResourceType=instance,Tags=[{Key=owner,Value=azure_devops}]"}"

    if [[ -n "$security_group" ]]; then
        instance_id=$(aws ec2 run-instances --region "$region" --image-id "$instance_os" --instance-type "$instance_size" --security-groups "$security_group" --tag-specifications "$tag_specifications" --output json | jq -r '.Instances[0].InstanceId')
    elif [[ -n "$subnet" ]]; then
        instance_id=$(aws ec2 run-instances --region "$region" --image-id "$instance_os" --instance-type "$instance_size" --subnet-id "$subnet" --tag-specifications "$tag_specifications" --output json | jq -r '.Instances[0].InstanceId')
    fi

    if [[ -n "$instance_id" ]]; then
        if aws ec2 wait instance-running --region "$region" --instance-ids "$instance_id"; then
            echo "$instance_id"
        fi
    fi
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
#   - the instance id is returned if no errors occurred
#
# Usage: delete_ec2 <instance_id> <region>
delete_ec2() {
    local instance_id=$1
    local region=$2

    if aws ec2 terminate-instances --region "$region" --instance-ids "$instance_id"; then
        if aws ec2 wait instance-terminated --region "$region" --instance-ids "$instance_id"; then
            echo "$instance_id"
        fi
    fi
}

# Description:
#   This function is used to retrieve a security group by tags
#
# Parameters:
#   - $1: The region where the security group is located (e.g. us-east-1)
#   - $2: The tags filters to use (e.g. "Name=tag:name,Values=create-delete-vm-sg")
#
# Usage: get_security_group_by_tags <region> <tags>
get_security_group_by_tags() {
    local region=$1
    local tags=$2

    aws ec2 describe-security-groups --region "$region" --filters "$tags" --output json | jq -r '.SecurityGroups[0].GroupId'
}

# Description:
#   This function is used to retrieve a subnet by tags
#
# Parameters:
#   - $1: The region where the subnet is located (e.g. us-east-1)
#   - $2: The tags filters to use (e.g. "Name=tag:name,Values=create-delete-vm-subnet")
#
# Usage: get_subnet_by_tags <region> <tags>
get_subnet_by_tags() {
    local region=$1
    local tags=$2

    aws ec2 describe-subnets --region "$region" --filters "$tags" --output json | jq -r '.Subnets[0].SubnetId'
}
