## Overview

This guide covers how to manually run vm iperf test on Azure

### Prerequisite
* Install Terraform (https://developer.hashicorp.com/terraform/tutorials/aws-get-started/install-cli)
* Install Azure CLI (https://learn.microsoft.com/en-us/cli/azure/install-azure-cli-linux?pivots=apt)
* Install [jq - 1.6-2.1ubuntu3](https://stedolan.github.io/jq/download/)

### Define Variables
Set environment variables for testing
```bash
SCENARIO_TYPE=perf-eval
SCENARIO_NAME=bm-iperf3
RUN_ID=01102024
OWNER=$(whoami)
RESULT_PATH=/tmp/$RUN_ID
CLOUD=azure
REGION=eastus2
MACHINE_TYPE=Standard_E112iads_v5
ACCERLATED_NETWORKING=true
SERVER_ROLE=server
CLIENT_ROLE=client
TERRAFORM_MODULES_DIR=modules/terraform/$CLOUD
TEST_MODULES_DIR=modules/bash
USER_DATA_PATH=$(pwd)/scenarios/$SCENARIO_TYPE/$SCENARIO_NAME/bash-scripts
TERRAFORM_INPUT_FILE=$(pwd)/scenarios/$SCENARIO_TYPE/$SCENARIO_NAME/terraform-inputs/$CLOUD.tfvars
SSH_KEY_PATH=$(pwd)/modules/terraform/$CLOUD/private_key.pem
SSH_PORT=2222
ADMIN_USERNAME=azureuser
```

### Provision Resources

Login into Azure account and set subscription for testing
```bash
az login
az account set --subscription <subscriptionId>
```

If this is on a un-managed device without web browser like Linux devbox, please create a service principle first
```bash
az ad sp create-for-rbac --name <servicePrincipleName> --role contributor --scopes /subscriptions/<subscriptionId>
{
  "appId": "xxx",
  "displayName": "xxx",
  "password": "xxx",
  "tenant": "xxx"
}
```

and then login with service principle
```bash
az login --service-principal --username <appId> --password <password> --tenant <tenant>
```

Create Resource Group for testing

```bash
az group create --name $RUN_ID --location $REGION --tags "run_id=$RUN_ID" "scenario=${SCENARIO_TYPE}-${SCENARIO_NAME}" "owner=$OWNER" "creation_date=$(date -u +'%Y-%m-%dT%H:%M:%SZ')" "deletion_due_time=$(date -u -d '+2 hour' +'%Y-%m-%dT%H:%M:%SZ')"
```

Provision test resources using terraform
```bash
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
terraform apply -var json_input=$(echo $INPUT_JSON | jq -c .) -var-file $TERRAFORM_INPUT_FILE --auto-approve
popd
```

### Validate Resources
Validate server VM is running and ready for iperf traffic
```bash
SERVER_VM_ID=$(az resource list --resource-type Microsoft.Compute/virtualMachines --query "[?(tags.run_id == '${RUN_ID}' && tags.role == '${SERVER_ROLE}')].id" --output tsv)
SERVER_PUBLIC_IP=$(az vm list-ip-addresses --ids $SERVER_VM_ID --query '[].virtualMachine.network.publicIpAddresses[0].ipAddress' -o tsv)
SERVER_PRIVATE_IP=$(az vm list-ip-addresses --ids $SERVER_VM_ID --query '[].virtualMachine.network.privateIpAddresses[0]' -o tsv)
```

Validate client VM is running and ready for iperf traffic
```bash
CLIENT_VM_ID=$(az resource list --resource-type Microsoft.Compute/virtualMachines --query "[?(tags.run_id == '${RUN_ID}' && tags.role == '${CLIENT_ROLE}')].id" --output tsv)
CLIENT_PUBLIC_IP=$(az vm list-ip-addresses --ids $CLIENT_VM_ID --query '[].virtualMachine.network.publicIpAddresses[0].ipAddress' -o tsv)
CLIENT_PRIVATE_IP=$(az vm list-ip-addresses --ids $CLIENT_VM_ID --query '[].virtualMachine.network.privateIpAddresses[0]' -o tsv)
```

### Execute Tests
Run iperf for both TCP and UDP test traffic with target bandwidth at 100Mbps, 1Gbps, 2Gbps, 4Gbps

Setup Iperf properties for TCP and UDP 
```bash
- "tcp|100|1|--client $(SERVER_PRIVATE_IP) --time 600 --bandwidth 100M --parallel 1 -w 640k"
- "tcp|1000|1|--client $(SERVER_PRIVATE_IP) --time 600 --bandwidth 1000M --parallel 1 -w 640k"
- "tcp|2000|2|--client $(SERVER_PRIVATE_IP) --time 600 --bandwidth 1000M --parallel 2 -w 640k"
- "tcp|4000|4|--client $(SERVER_PRIVATE_IP) --time 600 --bandwidth 1000M --parallel 4 -w 640k"
- "udp|100|1|--client $(SERVER_PRIVATE_IP) --time 600 --udp --bandwidth 100M --parallel 1"
- "udp|1000|1|--client $(SERVER_PRIVATE_IP) --time 600 --udp --bandwidth 1000M --parallel 1"
- "udp|2000|1|--client $(SERVER_PRIVATE_IP) --time 600 --udp --bandwidth 2000M --parallel 1"
- "udp|4000|1|--client $(SERVER_PRIVATE_IP) --time 600 --udp --bandwidth 4000M --parallel 1"
```

```bash
source ./${TEST_MODULES_DIR}/iperf.sh
run_iperf3 $SERVER_PRIVATE_IP $CLIENT_PUBLIC_IP $ADMIN_USERNAME $SSH_PORT $SSH_KEY_PATH $RESULT_PATH $PROTOCOL $BANDWIDTH $IPERF_PROPERTIES
```

### Collect Results
Collect and parse iperf output and Linux counters, merge into a single result JSON file
```bash
collect_result_iperf3 $RESULT_PATH $CLIENT_PRIVATE_IP $SERVER_PRIVATE_IP $RUN_ID $PROTOCOL $BANDWIDTH
```

Check the results
```bash
cat $RESULT_PATH/results.json | jq .
```

### Cleanup Resources
Cleanup test resources using terraform
```bash
pushd $TERRAFORM_MODULES_DIR
terraform destroy -var json_input=$(echo $INPUT_JSON | jq -c .) -var-file $TERRAFORM_INPUT_FILE
popd
```

After terraform destroys all the resources delete resource group manually.

```bash
az group delete --name $RUN_ID
```

## References

* [IPerf-3](https://iperf.fr/iperf-doc.php#3doc)
* [Terraform Azure Provider](https://registry.terraform.io/providers/hashicorp/azurerm/latest/docs)
* [Azure CLI](https://learn.microsoft.com/en-us/cli/azure/reference-index?view=azure-cli-latest)
* [Azure Service Principle](https://docs.microsoft.com/en-us/cli/azure/create-an-azure-service-principal-azure-cli?view=azure-cli-latest)
* [Azure Portal](https://portal.azure.com/)