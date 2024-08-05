#!/bin/bash

# DESC: Get the ip of the instance
# ARGS: $1 (required): The instance id
# OUTS: The IP to STDOUT
# NOTE: None
aws::get_vm_ip() {
    local instance_id=$1

    aws ec2 describe-instances --instance-ids $instance_id \
     --query "Reservations[0].Instances[0].PublicIpAddress" --output text
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
    local ssh_port=${4:-"2222"}
    local timeout=${5:-"500"}

    start_time=$(date +%s)

    (
        aws ec2 stop-instances --instance-id "$instance_id" 
        aws ec2 wait instance-stopped --instance-ids $instance_id

        sleep $wait_time

        aws ec2 start-instances --instance-id $instance_id 
        aws ec2 wait instance-running --instance-ids $instance_id
    ) 1> /dev/null 2>>$error_file
    echo "VM $instance_id was start/stopped successfully " >&2
    # the ip changes after redeploy that's why we get here the new ip
    echo "Trying to netcat into port $ssh_port on $instance_id" >&2
    current_ip=$(aws::get_vm_ip "$instance_id")
    connection_successful=$(utils::test_connection $current_ip $ssh_port $timeout) 
    if [ "$connection_successful" == "false" ]; then
        echo "SSH TIMEOUT" >>$error_file
    fi

    end_time=$(date +%s)
    echo "Total time form $instance_id $(($end_time - $start_time - $wait_time))" >&2
    echo "$(($end_time - $start_time - $wait_time))"
}