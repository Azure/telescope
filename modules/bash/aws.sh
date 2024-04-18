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
  echo "$ROLE Public IP Address: $lb_dns_name" >&2
  echo  $lb_dns_name
}

aws_create_vpc_peering(){
  local run_id=$1
  local client_vpc_region=$2
  local server_vpc_region=$3
  local deletion_due_time=$4
  local owner=$5
  local creation_time=$6
  local scenario=$7

  # Step 1: Check for the VPC IDs of the Server and Client VPC 
  echo "Checking for VPC with run Id $run_id"
  client_vpc_id=$(aws ec2 describe-vpcs --region $client_vpc_region --filters "Name=tag:run_id,Values=$run_id" --query "Vpcs[0].VpcId" --output text)
  server_vpc_id=$(aws ec2 describe-vpcs --region $server_vpc_region --filters "Name=tag:run_id,Values=$run_id" --query "Vpcs[0].VpcId" --output text)

  echo "Server ID $server_vpc_id Client ID $client_vpc_id "

  # Step 2: Create VPC peering connection between client and server VPCs
  echo "Creating VPC peering connection between $client_vpc_id ($client_vpc_region) and $server_vpc_id ($server_vpc_region)"

  peering_id=$(aws ec2 create-vpc-peering-connection \
    --vpc-id $client_vpc_id \
    --region $client_vpc_region \
    --peer-vpc-id $server_vpc_id \
    --peer-region $server_vpc_region \
    --tag-specifications "ResourceType=vpc-peering-connection,Tags=[{Key=run_id,Value=${run_id}},{Key=deletion_due_time,Value=${deletion_due_time}},{Key=owner,Value=${owner}},{Key=creation_time,Value=${creation_time}},{Key=scenario,Value=${scenario}}]" \
    --query "VpcPeeringConnection.VpcPeeringConnectionId" --output text)

  # Wait until the peering connection is available
  aws ec2 wait vpc-peering-connection-exists --region $client_vpc_region --vpc-peering-connection-ids $peering_id 

  # Step 3 Accept the Peering after it's been created. 
  echo "Accepting Peering ID $peering_id"
  accept_peering_retry=5
  accept_peering_interval=10
  for ((i=1; i<=$accept_peering_retry; i++)); do
    if aws ec2 accept-vpc-peering-connection --vpc-peering-connection-id $peering_id --region $server_vpc_region; then
      echo "Peering connection accepted successfully."
      break
    else
      echo "Failed to accept peering connection. Retrying in $accept_peering_interval seconds..."
      sleep $accept_peering_interval
    fi
  done

  # Step 4 Modify internet-rt Route Tables for both VPCs to go to the peering connection   
  client_route_table=$(aws ec2 describe-route-tables --region $client_vpc_region --query "RouteTables[?VpcId=='$client_vpc_id' && Tags[?Key=='Name' && Value=='internet-rt']].RouteTableId" --output text)
  server_route_table=$(aws ec2 describe-route-tables --region $server_vpc_region --query "RouteTables[?VpcId=='$server_vpc_id' && Tags[?Key=='Name' && Value=='internet-rt']].RouteTableId" --output text)

  client_cidr_block=$(aws ec2 describe-vpcs --region $client_vpc_region --vpc-ids $client_vpc_id --query 'Vpcs[0].CidrBlock' --output text)
  server_cidr_block=$(aws ec2 describe-vpcs --region $server_vpc_region --vpc-ids $server_vpc_id --query 'Vpcs[0].CidrBlock' --output text)

  aws ec2 create-route --route-table-id $client_route_table --region $client_vpc_region --destination-cidr-block $server_cidr_block --vpc-peering-connection-id $peering_id
  aws ec2 create-route --route-table-id $server_route_table --region $server_vpc_region --destination-cidr-block $client_cidr_block --vpc-peering-connection-id $peering_id

  #Verify Route table is updated 
  aws ec2 describe-route-tables --route-table-ids $client_route_table --region $client_vpc_region
  aws ec2 describe-route-tables --route-table-ids $server_route_table --region $server_vpc_region
}

aws_eks_deploy_fio()
{
  local region=$1
  local eksName=$2
  local scenario_type=$3
  local scenario_name=$4
  local disk_type=$5
  local disk_size_in_gb=$6
  local replica_count=$7
  local data_disk_iops_read_write=$8
  local data_disk_mbps_read_write=$9

  aws eks update-kubeconfig --region $region --name $eksName
  local file_source=./scenarios/${scenario_type}/${scenario_name}/yml-files/aws

  delete_time=$(date -ud '+2 hour' +'%FT%TZ')
  deletion_tag="deletion_due_time=${delete_time}"

  if [ -z "$data_disk_iops_read_write" ]; then
    sed -i "s/\(type: \).*/\1$disk_type/" "${file_source}/storage-class.yml"
    sed -i "s/\(tagSpecification_1: \).*/\1\"$deletion_tag\"/" "${file_source}/storage-class.yml"
    kubectl apply -f "${file_source}/storage-class.yml"
  else
    sed -i "s/\(type: \).*/\1$disk_type/" "${file_source}/storage-class-provisioned.yml"
    sed -i "s/\(iops: \).*/\1\"$data_disk_iops_read_write\"/" "${file_source}/storage-class-provisioned.yml"
    sed -i "s/\(throughput: \).*/\1\"$data_disk_mbps_read_write\"/" "${file_source}/storage-class-provisioned.yml"
    sed -i "s/\(tagSpecification_1: \).*/\1\"$deletion_tag\"/" "${file_source}/storage-class-provisioned.yml"
    kubectl apply -f "${file_source}/storage-class-provisioned.yml"
  fi


  sed -i "s/\(storage: \).*/\1${disk_size_in_gb}Gi/" "${file_source}/pvc.yml"
  sed -i "s/\(replicas: \).*/\1$replica_count/" "${file_source}/fio.yml"
  
  kubectl apply -f "${file_source}/pvc.yml"
  kubectl apply -f "${file_source}/fio.yml"
}

aws_eks_deploy_fio_fileshare()
{
  local region=$1
  local eksName=$2
  local scenario_type=$3
  local scenario_name=$4
  local fileSystemId=$5
  local replica_count=$6

  aws eks update-kubeconfig --region $region --name $eksName
  local file_source=./scenarios/${scenario_type}/${scenario_name}/yml-files/aws

  delete_time=$(date -ud '+2 hour' +'%FT%TZ')
  deletion_tag="deletion_due_time=${delete_time}"

  sed -i "s/\(fileSystemId: \).*/\1$fileSystemId/" "${file_source}/storage-class.yml"
  sed -i "s/\(tagSpecification_1: \).*/\1\"$deletion_tag\"/" "${file_source}/storage-class.yml"
  kubectl apply -f "${file_source}/storage-class.yml"

  sed -i "s/\(replicas: \).*/\1$replica_count/" "${file_source}/fio.yml"
  
  kubectl apply -f "${file_source}/pvc.yml"
  kubectl apply -f "${file_source}/fio.yml"
}