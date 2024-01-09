## Overview

This guide covers how to manually reproduce load balancer TLS handshake issue on Azure

### Prerequisite
* Install Terraform (https://developer.hashicorp.com/terraform/tutorials/aws-get-started/install-cli)
* Install Azure CLI (https://learn.microsoft.com/en-us/cli/azure/install-azure-cli-linux?pivots=apt)

### Define Variables
Set environment variables for testing
```
SCENARIO_TYPE=issue-repro
SCENARIO_NAME=lb-tls-error
RUN_ID=01092024
OWNER=$(whoami)
RESULT_PATH=/tmp/$RUN_ID
CLOUD=azure
REGION=eastus
MACHINE_TYPE=Standard_D2s_v5
ACCERLATED_NETWORKING=true
INGRESS_ROLE=ingress
CLIENT_NAME=client-vm
TERRAFORM_MODULES_DIR=modules/terraform/$CLOUD
SCRIPT_MODULES_DIR=modules/bash
USER_DATA_PATH=$(pwd)/scenarios/$SCENARIO_TYPE/$SCENARIO_NAME/bash-scripts
TERRAFORM_INPUT_FILE=$(pwd)/scenarios/$SCENARIO_TYPE/$SCENARIO_NAME/terraform-inputs/$CLOUD.tfvars
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
Validate Standard Load Balancer (SLB) is running and ready for traffic
```
SLB_ID=$(az resource list --resource-type Microsoft.Network/loadBalancers --query "[?(tags.run_id == '${RUN_ID}' && tags.role == '$INGRESS_ROLE')].id" --output tsv)
SLB_PIP_ID=$(az network lb show --ids $SLB_ID --query frontendIPConfigurations[0].publicIPAddress.id --output tsv)
SLB_PUBLIC_IP=$(az network public-ip show --ids $SLB_PIP_ID --query ipAddress -o tsv)
```

### Execute Tests
Run client sending HTTPs traffic to simulate TCP connections with TLS handshake through Azure standard load balancer
```
az vm run-command create --name dockerCommand -g ${RUN_ID} --vm-name ${CLIENT_NAME} --async-execution true --script "docker run -e SERVER_ADDRESS=${SLB_PUBLIC_IP}" telescope.azurecr.io/issue-repro/slb-eof-error-client:v1.0.9
{
  "asyncExecution": true,
  "errorBlobUri": null,
  "id": "/subscriptions/c0d4b923-b5ea-4f8f-9b56-5390a9bf2248/resourceGroups/01092024/providers/Microsoft.Compute/virtualMachines/client-vm/runCommands/dockerCommand",
  "instanceView": null,
  "location": "eastus",
  "name": "dockerCommand",
  "outputBlobUri": null,
  "parameters": null,
  "protectedParameters": null,
  "provisioningState": "Succeeded",
  "resourceGroup": "01092024",
  "runAsPassword": null,
  "runAsUser": null,
  "source": {
    "commandId": null,
    "script": "docker run -e SERVER_ADDRESS=20.163.235.127 -e TOTAL_CONNECTIONS 10000 telescope.azurecr.io/issue-repro/slb-eof-error-client:v1.0.9",
    "scriptUri": null
  },
  "tags": null,
  "timeoutInSeconds": 0,
  "type": "Microsoft.Compute/virtualMachines/runCommands"
}
```
Then wait for the test to finish execution
```
az vm run-command wait -g ${RUN_ID} --vm-name ${CLIENT_NAME} --run-command-name dockerCommand --instance-view --custom instanceView.endTime!=null
```

### Collect Results
Get the test execution by running command as below:
```
az vm run-command show -g ${RUN_ID} --vm-name ${CLIENT_NAME} --run-command-name dockerCommand --instance-view --query instanceView
```
if executionState field is succeeded, check output field for test results

### Cleanup Resources
Cleanup test resources using terraform
```
pushd $TERRAFORM_MODULES_DIR
terraform destroy -var json_input=$(echo $INPUT_JSON | jq -c .) -var-file $TERRAFORM_INPUT_FILE
popd
```