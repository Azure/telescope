#!/bin/bash

source ./modules/bash/utils.sh

aws_check_target() {
  local target_group_name=$1; shift
  local target_suffix_array=("$@")

  echo "Check target health"
  for target in "${target_suffix_array[@]}"
  do
    max_retries=10
    i=0
    name="${target_group_name}-$target"
    echo "Target group name: $name"

    while true
    do
      nlb_target_group_arn=$(aws elbv2 describe-target-groups --names $name --query 'TargetGroups[0].TargetGroupArn' --output text)
      echo "Target group ARN: $nlb_target_group_arn"
      nlb_target_group_health=$(aws elbv2 describe-target-health --target-group-arn $nlb_target_group_arn --query 'TargetHealthDescriptions[0].TargetHealth' --output text)
      echo "Target group health: $nlb_target_group_health"
      i=$((i+1))

      if [ "$nlb_target_group_health" = "healthy" ]; then
        break
      elif [ "$i" -eq "$max_retries" ]; then
        echo "Target group $name not healthy after $max_retries retries"
        exit 1
      fi
      
      sleep 30
    done
  done
}

aws_check_ec2() {
  local instance_name=$1

  echo "Check ec2 health for $instance_name"
  instance_id=$(aws ec2 describe-instances --filters "Name=tag:Name,Values=$instance_name" --query "Reservations[].Instances[].InstanceId[]" --output text)
  if [ -z "$instance_id" ]; then
    echo "No instance with name $instance_name found."
    exit 1
  fi

  echo "Waiting for EC2 instance $instance_id to be running..."
  aws ec2 wait instance-running --instance-ids $instance_id

  max_retries=10
  i=0
  while true; do
      instance_status=$(aws ec2 describe-instance-status --instance-ids $instance_id --query 'InstanceStatuses[*].InstanceStatus.Status' --output text)

      if [ "$instance_status" = "ok" ]; then
        echo "EC2 instance $instance_id is healthy."
        break
      elif [ "$i" -eq "$max_retries" ]; then
        echo "EC2 instance $instance_id not healthy after $max_retries retries"
        exit 1
      else
        echo "EC2 instance $instance_id is not healthy yet. Waiting for 30 seconds before checking again..."
        sleep 30
      fi
      i=$((i+1))
  done
}

aws_instance_ip_address() {
  local instance_name=$1
  local ip_type=$2

  if [ "$ip_type" == "public" ]; then
    ip_address=$(aws ec2 describe-instances --filters Name=tag:Name,Values=$instance_name --query 'Reservations[0].Instances[0].PublicIpAddress' --output text)
  elif [ "$ip_type" == "private" ]; then
    ip_address=$(aws ec2 describe-instances --filters Name=tag:Name,Values=$instance_name --query 'Reservations[0].Instances[0].PrivateIpAddress' --output text)
  else
    ip_address="invalid ip type $ip_type"
  fi

  echo $ip_address
}

aws_lb_dns_name() {
  local load_balancer_name=$1

  dns_name=$(aws elbv2 describe-load-balancers --names $load_balancer_name --query 'LoadBalancers[0].DNSName' --output text)
  echo $dns_name
}
