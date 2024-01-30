## Overview

This guide covers how to manually run vm iperf test on Azure

### Prerequisite
* Install Terraform (https://developer.hashicorp.com/terraform/tutorials/aws-get-started/install-cli)
* Install Azure CLI (https://learn.microsoft.com/en-us/cli/azure/install-azure-cli-linux?pivots=apt)

### Define Variables
Set environment variables for testing
```
SCENARIO_TYPE=perf-eval
SCENARIO_NAME=vm-iperf
RUN_ID=01042024
OWNER=$(whoami)
RESULT_PATH=/tmp/$RUN_ID
CLOUD=azure
REGION=eastus
MACHINE_TYPE=standard_D16_v3
ACCERLATED_NETWORKING=true
SERVER_ROLE=server
CLIENT_ROLE=client
TERRAFORM_MODULES_DIR=modules/terraform/$CLOUD
TEST_MODULES_DIR=modules/bash
USER_DATA_PATH=$(pwd)/scenarios/$SCENARIO_TYPE/$SCENARIO_NAME/bash-scripts
TERRAFORM_INPUT_FILE=$(pwd)/scenarios/$SCENARIO_TYPE/$SCENARIO_NAME/terraform-inputs/$CLOUD.tfvars
SSH_KEY_PATH=$(pwd)/modules/terraform/$CLOUD/private_key.pem
TCP_THREAD_MODE=multi
UDP_THREAD_MODE=single
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
--arg owner $OWNER \
--arg run_id $RUN_ID \
--arg region $REGION \
--arg machine_type $MACHINE_TYPE \
--arg accelerated_networking $ACCERLATED_NETWORKING \
--arg user_data_path $USER_DATA_PATH \
'{owner: $owner, run_id: $run_id, region: $region, machine_type: $machine_type, accelerated_networking: $accelerated_networking,user_data_path:$user_data_path}')

pushd $TERRAFORM_MODULES_DIR
terraform init
terraform apply -var json_input=$(echo $INPUT_JSON | jq -c .) -var-file $TERRAFORM_INPUT_FILE
popd
```

### Validate Resources
Validate server VM is running and ready for iperf traffic
```
SERVER_VM_ID=$(az resource list --resource-type Microsoft.Compute/virtualMachines --query "[?(tags.run_id == '${RUN_ID}' && tags.role == '${SERVER_ROLE}')].id" --output tsv)
SERVER_PUBLIC_IP=$(az vm list-ip-addresses --ids $SERVER_VM_ID --query '[].virtualMachine.network.publicIpAddresses[0].ipAddress' -o tsv)
SERVER_PRIVATE_IP=$(az vm list-ip-addresses --ids $SERVER_VM_ID --query '[].virtualMachine.network.privateIpAddresses[0]' -o tsv)
```

Validate client VM is running and ready for iperf traffic
```
CLIENT_VM_ID=$(az resource list --resource-type Microsoft.Compute/virtualMachines --query "[?(tags.run_id == '${RUN_ID}' && tags.role == '${CLIENT_ROLE}')].id" --output tsv)
CLIENT_PUBLIC_IP=$(az vm list-ip-addresses --ids $CLIENT_VM_ID --query '[].virtualMachine.network.publicIpAddresses[0].ipAddress' -o tsv)
CLIENT_PRIVATE_IP=$(az vm list-ip-addresses --ids $CLIENT_VM_ID --query '[].virtualMachine.network.privateIpAddresses[0]' -o tsv)
```

### Execute Tests
Run iperf for both TCP and UDP test traffic with target bandwidth at 100Mbps, 1Gbps, 2Gbps, 4Gbps
```
source ./${TEST_MODULES_DIR}/iperf.sh
run_iperf2 $SERVER_PRIVATE_IP $CLIENT_PUBLIC_IP $TCP_THREAD_MODE $UDP_THREAD_MODE $SSH_KEY_PATH $SERVER_PUBLIC_IP $RESULT_PATH
```


### Collect Results
Collect and parse iperf output and Linux counters, merge into a single result JSON file
```
collect_result_iperf2 $RESULT_PATH $CLIENT_PRIVATE_IP $SERVER_PRIVATE_IP $CLOUD $RUN_ID
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