## Overview

This guide covers how to manually run vm -> pe -> storage account https test on Azure and AWS

### Prerequisite
* Install Terraform (https://developer.hashicorp.com/terraform/tutorials/aws-get-started/install-cli)
* Install Azure CLI (https://learn.microsoft.com/en-us/cli/azure/install-azure-cli-linux?pivots=apt)
* Install AWS Cli (https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html)

## Azure Side
### Define Variables
Set environment variables for testing
```
CLOUD=azure
ssh_key_path=$(pwd)/modules/terraform/$CLOUD/private_key.pem
ssh-keygen -t rsa -b 2048 -f $ssh_key_path -N ""
SSH_PUBLIC_KEY_PATH="${ssh_key_path}.pub"
export SCENARIO_TYPE=perf-eval
export SCENARIO_NAME=vm-pe-storage
export RUN_ID=0003
export OWNER=$(whoami)
export RESULT_PATH=/tmp/$RUN_ID
export TEMP_JMETER=/tmp/jmeter
export CLOUD=azure
export REGION=eastus
export MACHINE_TYPE=Standard_D2s_v5
export ACCERLATED_NETWORKING=true
export CLIENT_ROLE=client
export TERRAFORM_MODULES_DIR=modules/terraform/$CLOUD
export TEST_MODULES_DIR=modules/bash
export USER_DATA_PATH=$(pwd)/scenarios/$SCENARIO_TYPE/$SCENARIO_NAME/bash-scripts
export TERRAFORM_INPUT_FILE=$(pwd)/scenarios/$SCENARIO_TYPE/$SCENARIO_NAME/terraform-inputs/$CLOUD.tfvars
export SSH_KEY_PATH=$(pwd)/modules/terraform/$CLOUD/private_key.pem
export STORAGE_ACCOUNT_TIER=Standard
export STORAGE_ACCOUNT_REPLICATION_TYPE=LRS
export STORAGE_SHARE_ENABLED_PROTOCOL=NFS
```

### Provision Resources

Login into Azure account and set subscription for testing
```
az login
az account set --subscription <subscriptionId>
```

If this is on a un-managed device without web browser like Linux devbox, please create a service principle first
```
az ad sp create-for-rbac --name <servicePrincipleName> --role contributor --scopes /subscriptions/<subscriptionId>
{
  "appId": "xxx",
  "displayName": "xxx",
  "password": "xxx",
  "tenant": "xxx"
}
```

and then login with service principle
```
az login --service-principal --username <appId> --password <password> --tenant <tenant>
```

Provision test resources using terraform
```
INPUT_JSON=$(jq -n \
--arg owner "$OWNER" \
--arg run_id "$RUN_ID" \
--arg region "$REGION" \
--arg machine_type "$MACHINE_TYPE" \
--arg accelerated_networking "$ACCERLATED_NETWORKING" \
--arg user_data_path "$USER_DATA_PATH" \
--arg public_key_path "$SSH_PUBLIC_KEY_PATH" \
--arg storage_account_tier "$STORAGE_ACCOUNT_TIER" \
--arg storage_account_replication_type "$STORAGE_ACCOUNT_REPLICATION_TYPE" \
--arg storage_share_enabled_protocol "$STORAGE_SHARE_ENABLED_PROTOCOL" \
'{owner: $owner, run_id: $run_id, region: $region, machine_type: $machine_type, accelerated_networking: $accelerated_networking,user_data_path:$user_data_path,public_key_path:$public_key_path,storage_account_tier:$storage_account_tier,storage_account_replication_type:$storage_account_replication_type,storage_share_enabled_protocol:$storage_share_enabled_protocol}')
 
az group create --name $RUN_ID --location $REGION --tags "run_id=$RUN_ID" "scenario=${SCENARIO_TYPE}-${SCENARIO_NAME}" "owner=azure_devops" "creation_date=$(date -u +'%Y-%m-%dT%H:%M:%SZ')" "deletion_due_time=$(date -u -d '+2 hour' +'%Y-%m-%dT%H:%M:%SZ')"

pushd $TERRAFORM_MODULES_DIR
terraform init
terraform plan -var json_input=$(echo $INPUT_JSON | jq -c .) -var-file $TERRAFORM_INPUT_FILE
terraform apply -var json_input=$(echo $INPUT_JSON | jq -c .) -var-file $TERRAFORM_INPUT_FILE --auto-approve
popd
```

### Validate Resources
Validate client VM is running and ready for https traffic
```
VM_ID=$(az resource list --resource-type Microsoft.Compute/virtualMachines --query "[?(tags.run_id == '${RUN_ID}' && tags.role == '${CLIENT_ROLE}')].id" --output tsv)
VM_PUBLIC_IP=$(az vm list-ip-addresses --ids $VM_ID --query '[].virtualMachine.network.publicIpAddresses[0].ipAddress' -o tsv)
```

Validate pe is deployed and ready for https traffic
```
PE_ID=$(az resource list --resource-type Microsoft.Network/privateEndpoints --query "[?(resourceGroup == '${RUN_ID}')].id" -o tsv)
PE_IP=$(az network private-endpoint show --ids $PE_ID --query 'customDnsConfigs[0].ipAddresses[0]' -o tsv)
```

Validate storage account name and create Azure REST API endpoint
```
STORAGE_NAME=$(az storage account list --resource-group $RUN_ID --query '[].name' -o tsv)
STORAGE_KEY=$(az storage account keys list -g $RUN_ID -n $STORAGE_NAME --query '[0].value' -o tsv)
STORAGE_CONTAINER=$(az storage container list --account-name $STORAGE_NAME --account-key $STORAGE_KEY --query '[].name' -o tsv)
STORAGE_BLOB=$(az storage blob list --account-name $STORAGE_NAME --container-name $STORAGE_CONTAINER --account-key $STORAGE_KEY --query '[].name' -o tsv)
```

### Execute Tests
Leverage scp to transfer jmeter properties and text.jmx files to client vm
```
source ./${TEST_MODULES_DIR}/jmeter.sh

run_scp_remote $ssh_key_path ubuntu $VM_PUBLIC_IP 2222 "${USER_DATA_PATH}/jmeter.properties" "${TEMP_JMETER}/jmeter.properties"
run_scp_remote $ssh_key_path ubuntu $VM_PUBLIC_IP 2222 "${USER_DATA_PATH}/${CLOUD}/https_test.jmx" "${TEMP_JMETER}/https_test.jmx"

mkdir -p $RESULT_PATH
```

Execute jmeter test for single thread @ 100 loops (this is a constraint of Azure REST Api, after an undisclosed amount of request, the api will continuously return 429 bad request responses)
```
JMETER__HTTPS_PROPERTY="-JProtocol=https -JPort=443 -Jthread_num=1 -Jloop_count=1 -Jrequest_delay=200 -Jstorage_account=$STORAGE_NAME -Jcontainer=$STORAGE_CONTAINER -Jblob=$STORAGE_BLOB -Jstorage_key=$STORAGE_KEY -Jxmsversion=2024-05-04"	
run_jmeter $VM_PUBLIC_IP $ssh_key_path https 1 "$JMETER_HTTP_PROPERTY" "$TEMP_JMETER" $RESULT_PATH
```

### Collect Results
Collect and parse jmeter https test result(s)
```
collect_result_jmeter https 1 $RESULT_PATH $RUN_ID "" ""
```

Check the results
```
cat $RESULT_PATH/results.json | jq .
```

### Cleanup Resources
Cleanup test resources using terraform
```
pushd $TERRAFORM_MODULES_DIR
terraform destroy -var json_input=$(echo $INPUT_JSON | jq -c .) -var-file $TERRAFORM_INPUT_FILE
popd
```

## AWS Side
### Define Variables
Set environment variables for testing
```
CLOUD=aws
ssh_key_path=$(pwd)/modules/terraform/$CLOUD/private_key.pem
ssh-keygen -t rsa -b 2048 -f $ssh_key_path -N ""
SSH_PUBLIC_KEY_PATH="${ssh_key_path}.pub"
SCENARIO_TYPE=perf-eval
SCENARIO_NAME=vm-pe-storage
RUN_ID=lbrookstest
OWNER=$(whoami)
CLOUD=aws
REGION=us-east-2
ZONE=us-east-2b
MACHINE_TYPE=m6i.4xlarge
export SERVER_ROLE=server
export CLIENT_ROLE=client
export TEST_MODULES_DIR=modules/bash
TERRAFORM_MODULES_DIR=modules/terraform/$CLOUD
TERRAFORM_USER_DATA_PATH=$(pwd)/scenarios/$SCENARIO_TYPE/$SCENARIO_NAME/bash-scripts
export USER_DATA_PATH=$(pwd)/scenarios/$SCENARIO_TYPE/$SCENARIO_NAME/bash-scripts
TERRAFORM_INPUT_FILE=$(pwd)/scenarios/$SCENARIO_TYPE/$SCENARIO_NAME/terraform-inputs/$CLOUD.tfvars
RESULT_PATH=/tmp/$RUN_ID
export TEMP_JMETER=/tmp/jmeter
BUCKET_NAME="$SCENARIO_NAME-$RUN_ID"
STORAGE_ENDPOINT="$BUCKET_NAME.s3.amazonaws.com"
```

### Provision Resources

Login into AWS account (you will need your access key ID and your access key secret value)
```
aws configure set aws_access_key_id $<your access key id>
aws configure set aws_secret_access_key $<your access key secret value>
aws configure set region us-east-2
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query 'Account' --output text)
```

Provision test resources using terraform
```
INPUT_JSON=$(jq -n \
--arg owner "$OWNER" \
  --arg run_id "$RUN_ID" \
  --arg region "$REGION" \
  --arg zone "$ZONE" \
  --arg machine_type "$MACHINE_TYPE" \
  --arg public_key_path "$SSH_PUBLIC_KEY_PATH" \
  --arg user_data_path $TERRAFORM_USER_DATA_PATH \
  '{ owner: $owner,run_id: $run_id,region: $region,zone: $zone,machine_type: $machine_type,public_key_path:$public_key_path,user_data_path: $user_data_path }' | jq 'with_entries(select(.value != null and .value != ""))')

pushd $TERRAFORM_MODULES_DIR
terraform init
terraform plan -var json_input=$(echo $INPUT_JSON | jq -c .) -var-file $TERRAFORM_INPUT_FILE
terraform apply -var json_input=$(echo $INPUT_JSON | jq -c .) -var-file $TERRAFORM_INPUT_FILE --auto-approve
popd
```

### Validate Resources
Validate client VM, VPC Endpoint, Routes all running and ready for https traffic
```
CLIENT_VM_ID=$(aws ec2 describe-instances --filters "Name=instance-state-name,Values=running" "Name=tag:run_id,Values=$RUN_ID" "Name=tag:role,Values=$CLIENT_ROLE" --query "Reservations[].Instances[].InstanceId[]" --output text)
CLIENT_PUBLIC_IP=$(aws ec2 describe-instances --instance-ids $CLIENT_VM_ID --query 'Reservations[0].Instances[0].PublicIpAddress' --output text)
CLIENT_PRIVATE_IP=$(aws ec2 describe-instances --instance-ids $CLIENT_VM_ID --query 'Reservations[0].Instances[0].PrivateIpAddress' --output text)
PRIVATE_ENDPOINT_ID=$(aws ec2 describe-vpc-endpoints --filters "Name=tag:run_id,Values=$RUN_ID" --query "VpcEndpoints[0].VpcEndpointId" --output text)
CLIENT_VPC_ID=$(aws ec2 describe-instances --instance-ids $CLIENT_VM_ID --query 'Reservations[0].Instances[0].VpcId' --output text)
INTERNET_ROUTE_TABLE_ID=$(aws ec2 describe-route-tables --filters "Name=vpc-id,Values=$CLIENT_VPC_ID" "Name=tag:Name,Values=internet-rt" --query "RouteTables[0].RouteTableId" --output text)
CLIENT_CIDR_BLOCK=$(aws ec2 describe-vpcs --vpc-ids $CLIENT_VPC_ID --query "Vpcs[0].CidrBlock" --output text)
aws ec2 modify-vpc-endpoint --vpc-endpoint-id $PRIVATE_ENDPOINT_ID --add-route-table-ids $INTERNET_ROUTE_TABLE_ID
DEST_PREFIX_LIST_ID=$(aws ec2 describe-route-tables --filters "Name=vpc-id,Values=$CLIENT_VPC_ID" "Name=tag:Name,Values=internet-rt" --query "RouteTables[0].Routes[2].DestinationPrefixListId" --output text)
PE_IP=$(aws ec2 describe-network-interfaces --filters "Name=vpc-id,Values=$CLIENT_VPC_ID" --query "NetworkInterfaces[0].PrivateIpAddress" --output text)
PE_IP=52.219.96.08
```

### Retrieve AWS Presign endpoint and separate substrings for jmeter
```
AWS_PRESIGN=$(aws s3 presign s3://vm-pe-storage-lbrookstest/test)
AWS_PATH=$(echo $AWS_PRESIGN | cut -c51-1000)
AWS_CREDENTIAL="$AWS_AK_ID/$(echo $AWS_PATH | cut -c132-139)/us-east-2/s3/aws4_request"
AWS_DATE=$(echo $AWS_PATH | cut -c132-147)
AWS_SIGNATURE=$(echo $AWS_PATH | cut -c209-500)
```

### Execute Tests
Leverage scp to transfer jmeter properties and text.jmx files to client vm
```
source ./${TEST_MODULES_DIR}/jmeter.sh

run_scp_remote $ssh_key_path ubuntu $VM_PUBLIC_IP 2222 "${USER_DATA_PATH}/jmeter.properties" "${TEMP_JMETER}/jmeter.properties"
run_scp_remote $ssh_key_path ubuntu $VM_PUBLIC_IP 2222 "${USER_DATA_PATH}/${CLOUD}/https_test.jmx" "${TEMP_JMETER}/https_test.jmx"

mkdir -p $RESULT_PATH
```

Execute jmeter test for single thread @ 100 loops (Due to a constraint of Azure REST Api, we also limit to AWS side with 1 thread 100 loops to maintain parity)
```
JMETER_HTTP_PROPERTY="-Jrequest_delay=200 -Jthread_num=1 -Jloop_count=100 -Jprotocol=https -Jport=443 -Jhttp_method=GET -Jaws_host=$STORAGE_ENDPOINT -Jaws_path=test -Jaws_credential=$AWS_CREDENTIAL -Jaws_date=$AWS_DATE -Jaws_signature=$AWS_SIGNATURE"
run_jmeter $VM_PUBLIC_IP $ssh_key_path https 1 "$JMETER_HTTP_PROPERTY" "$TEMP_JMETER" $RESULT_PATH
```

### Collect Results
Collect and parse jmeter https test result(s)
```
collect_result_jmeter https 1 $RESULT_PATH $RUN_ID "" ""
```

Check the results
```
cat $RESULT_PATH/results.json | jq .
```

### Cleanup Resources
Cleanup test resources using terraform
```
pushd $TERRAFORM_MODULES_DIR
terraform destroy -var json_input=$(echo $INPUT_JSON | jq -c .) -var-file $TERRAFORM_INPUT_FILE
popd
```