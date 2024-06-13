#!/bin/bash

# DESC: Get the instance view for a vm
# ARGS: $1 (required): The instance id of the VM
# OUTS: The json of the instance view
# NOTE: None
aws::get_vm_instance_view_json() {
    local instance_id=$1

    aws ec2 describe-instances --instance-ids $instance_id
}

# DESC: Get the ip of the instance
# ARGS: $1 (required): The instance id
# OUTS: The IP to STDOUT
# NOTE: None
aws::get_vm_ip() {
    local instance_id=$1

    aws ec2 describe-instances --instance-ids $instance_id \
     --query "Reservations[0].Instances[0].PublicIpAddress" --output text
}

# DESC: Get the instances from aws based on run_id from tags
# ARGS: $1 (required): The run_id from the pipeline
# OUTS: A list of instance ids to STDOUT
# NOTE: None
aws::get_vm_instances_name_by_run_id() {
    local run_id=$1

    aws ec2 describe-instances \
        --filters Name=tag:run_id,Values=$run_id Name=instance-state-name,Values=running \
        --query "Reservations[].Instances[0].InstanceId" \
        --output text
}

# DESC: Function for redeploying a VM in AWS
# ARGS: $1 (required): The instance-id of the VM
#       $2 (required): The path to the error file
#       $3 (optional): The wait time between stopping and starting the VM
#       $4 (optional): The ssh port of the VM
#       $5 (optional): The timeout for the connection test
# OUTS: Execution time of the redeploy
# NOTE: We wait some time (wait_time) between stop and start for maximizing the chance of the VM to end up in another node
#       We also subtract it, to not end in the total execution time
aws::redeploy_vm() {
    local instance_id=$1
    local error_file=$2
    local wait_time=${3:-"30"}
    local ssh_port=${4:-"22"}
    local timeout=${5:-"500"}

    start_time=$(date +%s)

    (
        aws ec2 stop-instances --instance-id "$instance_id" 
        aws ec2 wait instance-stopped --instance-ids $instance_id

        sleep $wait_time

        aws ec2 start-instances --instance-id $instance_id 
        aws ec2 wait instance-running --instance-ids $instance_id

        # the ip changes after redeploy that's why we get here the new ip
        current_ip=$(aws::get_vm_ip "$instance_id")
        connection_successful=$(utils::test_connection $current_ip $ssh_port $timeout) 
        if [ "$connection_successful" == "false" ]; then
            exit 1
        fi
    ) 1> /dev/null 2>>$error_file

    end_time=$(date +%s)

    echo "$(($end_time - $start_time - $wait_time))"
}