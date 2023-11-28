## Run Test Scenario

This guide covers how to run competitive tests manually, using vm-to-vm performnace evaluation on Azure as an example

### Prerequisite
* Install Terraform (https://developer.hashicorp.com/terraform/tutorials/aws-get-started/install-cli)
* Install Azure CLI (https://learn.microsoft.com/en-us/cli/azure/install-azure-cli-linux?pivots=apt)

### Define Test Variables
Set environment variables for testing
```
SCENARIO_NAME=perf-eval/vm-iperf
RUN_ID=10312023
OWNER=$(whoami)
RESULT_PATH=/tmp/$RUN_ID
RESOURCE_GROUP=test-$RUN_ID
CLOUD=azure
REGION=eastus
MACHINE_TYPE=standard_D16_v3
ACCERLATED_NETWORKING=true
SERVER_NAME=server-vm
CLIENT_NAME=client-vm
TERRAFORM_MODULES_DIR=modules/terraform/$CLOUD
SCRIPT_MODULES_DIR=modules/bash
USER_DATA_PATH=$(pwd)/scenarios/$SCENARIO_NAME/bash-scripts
TERRAFORM_INPUT_FILE=$(pwd)/scenarios/$SCENARIO_NAME/terraform-inputs/$CLOUD.tfvars
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
--arg location $REGION \
--arg resource_group_name $RESOURCE_GROUP \
--arg vm_sku $MACHINE_TYPE \
--arg accelerated_networking $ACCERLATED_NETWORKING \
--arg user_data_path $USER_DATA_PATH \
'{owner: $owner, run_id: $run_id, location: $location, resource_group_name: $resource_group_name, vm_sku: $vm_sku, accelerated_networking: $accelerated_networking,user_data_path:$user_data_path}')

pushd $TERRAFORM_MODULES_DIR
terraform init
terraform apply -var json_input=$(echo $INPUT_JSON | jq -c .) -var-file $TERRAFORM_INPUT_FILE
popd
```

### Validate Resources
Import bash module:
```
source ./${SCRIPT_MODULES_DIR}/utils.sh
source ./${SCRIPT_MODULES_DIR}/azure.sh
source ./${SCRIPT_MODULES_DIR}/iperf.sh
```

Validate server VM is running and ready for iperf traffic
```
SERVER_PUBLIC_IP=$(azure_vm_ip_address $RESOURCE_GROUP $SERVER_NAME "public")
SERVER_PRIVATE_IP=$(azure_vm_ip_address $RESOURCE_GROUP $SERVER_NAME "private")
check_iperf_setup $SERVER_PUBLIC_IP $IPERF_VERSION $SSH_KEY_PATH
```

Validate client VM is running and ready for iperf traffic
```
CLIENT_PUBLIC_IP=$(azure_vm_ip_address $RESOURCE_GROUP $CLIENT_NAME "public")
CLIENT_PRIVATE_IP=$(azure_vm_ip_address $RESOURCE_GROUP $CLIENT_NAME "private")
check_iperf_setup $CLIENT_PUBLIC_IP $IPERF_VERSION $SSH_KEY_PATH
```

### Execute Tests
Run iperf for both TCP and UDP test traffic with target bandwidth at 100Mbps, 1Gbps, 2Gbps, 4Gbps
```
run_iperf2 $SERVER_PRIVATE_IP $CLIENT_PUBLIC_IP $TCP_THREAD_MODE $UDP_THREAD_MODE $SSH_KEY_PATH $SERVER_PUBLIC_IP $RESULT_PATH
```


### Collect Results
Collect and parse iperf output and Linux counters, merge into a single result JSON file
```
collect_result_iperf2 $RESULT_PATH $RESOURCE_GROUP $REGION $MACHINE_TYPE $CLIENT_PRIVATE_IP $SERVER_PRIVATE_IP $RUN_ID
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