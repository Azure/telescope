#!/bin/bash

source ./modules/bash/utils.sh

aws_check_target() {
  local ROLE=$1
  local RUN_ID=$2

  echo "Check target health"
  target_group_arns=($(aws resourcegroupstaggingapi get-resources --tag-filters Key=run_id,Values=$RUN_ID Key=role,Values=$ROLE --resource-type-filters elasticloadbalancing:targetgroup --query ResourceTagMappingList[].ResourceARN --output text))

  for target in "${target_group_arns[@]}"
  do
    max_retries=10
    i=0
    echo "Target group ARN: $target"

    while true
    do
      target_group_health=$(aws elbv2 describe-target-health --target-group-arn $target --query 'TargetHealthDescriptions[0].TargetHealth.State' --output text)
      echo "Target group health: $target_group_health"
      i=$((i+1))

      if [ "$target_group_health" = "healthy" ]; then
        break
      elif [ "$i" -eq "$max_retries" ]; then
        echo "Target group $target not healthy after $max_retries retries"
        exit 1
      fi

      sleep 30
    done
  done
}

aws_check_ec2() {
  local ROLE=$1
  local RUN_ID=$2

  echo "Check ec2 health for instance with role $ROLE and tag $RUN_ID"  >&2
  instance_id=$(aws ec2 describe-instances --filters "Name=instance-state-name,Values=running" "Name=tag:run_id,Values=$RUN_ID" "Name=tag:role,Values=$ROLE" --query "Reservations[].Instances[].InstanceId[]" --output text)
  echo "Instance ID: $instance_id"  >&2
  if [ -z "$instance_id" ]; then
    echo "No instance with role $ROLE and tag $RUN_ID found."  >&2
    exit 1
  fi

  echo "Waiting for EC2 instance $instance_id to be running..."  >&2
  aws ec2 wait instance-running --instance-ids $instance_id

  max_retries=10
  i=0
  while true; do
      instance_status=$(aws ec2 describe-instance-status --instance-ids $instance_id --query 'InstanceStatuses[*].InstanceStatus.Status' --output text)

      if [ "$instance_status" = "ok" ]; then
        echo "EC2 instance $instance_id is healthy."  >&2
        echo $instance_id
        break
      elif [ "$i" -eq "$max_retries" ]; then
        echo "EC2 instance $instance_id not healthy after $max_retries retries"  >&2
        exit 1
      else
        echo "EC2 instance $instance_id is not healthy yet. Waiting for 30 seconds before checking again..."  >&2
        sleep 30
      fi
      i=$((i+1))
  done
}

aws_instance_ip_address() {
  local instance_id=$1
  local ip_type=$2
  
  if [ "$ip_type" == "public" ]; then
    ip_address=$(aws ec2 describe-instances --instance-ids $instance_id --query 'Reservations[0].Instances[0].PublicIpAddress' --output text)
  elif [ "$ip_type" == "private" ]; then
    ip_address=$(aws ec2 describe-instances --instance-ids $instance_id --query 'Reservations[0].Instances[0].PrivateIpAddress' --output text)
  else
    ip_address="invalid ip type $ip_type"
  fi

  echo $ip_address
}

aws_lb_dns_name() {
  local ROLE=$1
  local RUN_ID=$2

  lb_arn=$(aws resourcegroupstaggingapi get-resources --tag-filters Key=run_id,Values=$RUN_ID Key=role,Values=$ROLE --resource-type-filters elasticloadbalancing:loadbalancer --query ResourceTagMappingList[].ResourceARN --output text)
  echo "Load balancer ARN: $lb_arn" >&2

  lb_dns_name=$(aws elbv2 describe-load-balancers --load-balancer-arns $lb_arn --query LoadBalancers[].DNSName --output text)
  echo "$PREFIX Public IP Address: $lb_dns_name" >&2
  echo  $lb_dns_name
}
