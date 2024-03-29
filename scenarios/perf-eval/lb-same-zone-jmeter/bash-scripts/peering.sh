#!/bin/bash

RUN_ID=$1
OWNER=$2
client_region="us-east-2"
server_region="us-west-1"

client_vpc=$(aws ec2 describe-vpcs --region $client_region --filters "Name=tag:run_id,Values=${RUN_ID}" "Name=tag:role,Values=client" --query "Vpcs[*].VpcId" --output text)
echo "Client VPC: $client_vpc"

server_vpc=$(aws ec2 describe-vpcs --region $server_region --filters "Name=tag:run_id,Values=${RUN_ID}" "Name=tag:role,Values=server" --query "Vpcs[*].VpcId" --output text)
echo "Server VPC: $server_vpc"

deletion_due_time=$(aws ec2 describe-vpcs --region $client_region --vpc-ids $client_vpc --query "Vpcs[*].Tags[?Key=='deletion_due_time'].Value" --output text)

vpc_peering_id=$(aws ec2 create-vpc-peering-connection \
  --vpc-id $client_vpc \
  --region $client_region \
  --peer-vpc-id $server_vpc \
  --peer-region $server_region \
  --tag-specifications "ResourceType=vpc-peering-connection,Tags=[{Key=run_id,Value=${RUN_ID}},{Key=deletion_due_time,Value=${deletion_due_time}},{Key=owner,Value=${OWNER}}]" \
  --query "VpcPeeringConnection.VpcPeeringConnectionId" --output text)

aws ec2 wait vpc-peering-connection-exists \
  --vpc-peering-connection-ids $vpc_peering_id \
  --region $client_region

aws ec2 accept-vpc-peering-connection \
  --vpc-peering-connection-id $vpc_peering_id \
  --region $server_region

aws ec2 create-route \
  --route-table-id $(aws ec2 describe-route-tables --region $client_region --filters "Name=tag:run_id,Values=${RUN_ID}" --query "RouteTables[*].RouteTableId" --output text) \
  --destination-cidr-block $(aws ec2 describe-vpcs --region $server_region --vpc-ids $server_vpc --query "Vpcs[*].CidrBlock" --output text) \
  --vpc-peering-connection-id $vpc_peering_id \
  --region $client_region

aws ec2 create-route \
  --route-table-id $(aws ec2 describe-route-tables --region $server_region --filters "Name=tag:run_id,Values=${RUN_ID}" --query "RouteTables[*].RouteTableId" --output text) \
  --destination-cidr-block $(aws ec2 describe-vpcs --region $client_region --vpc-ids $client_vpc --query "Vpcs[*].CidrBlock" --output text) \
  --vpc-peering-connection-id $vpc_peering_id \
  --region $server_region

aws ec2 modify-vpc-peering-connection-options \
  --vpc-peering-connection-id $vpc_peering_id \
  --requester-peering-connection-options '{"AllowDnsResolutionFromRemoteVpc":true}' \
  --region $client_region

client_public_ip=$(aws ec2 describe-instances --region $client_region \
  --filters "Name=tag:run_id,Values=${RUN_ID}" "Name=tag:role,Values=client" \
  --query "Reservations[*].Instances[*].PublicIpAddress" --output text)

client_private_ip=$(aws ec2 describe-instances --region $client_region \
  --filters "Name=tag:run_id,Values=${RUN_ID}" "Name=tag:role,Values=client" \
  --query "Reservations[*].Instances[*].PrivateIpAddress" --output text)

server_public_ip=$(aws ec2 describe-instances --region $server_region \
  --filters "Name=tag:run_id,Values=${RUN_ID}" "Name=tag:role,Values=server" \
  --query "Reservations[*].Instances[*].PublicIpAddress" --output text)

server_private_ip=$(aws ec2 describe-instances --region $server_region \
  --filters "Name=tag:run_id,Values=${RUN_ID}" "Name=tag:role,Values=server" \
  --query "Reservations[*].Instances[*].PrivateIpAddress" --output text)