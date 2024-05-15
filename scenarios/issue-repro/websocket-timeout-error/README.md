## Overview

This guide covers how to manually reproduce WebSocket timeout issue on Azure

### Prerequisite

* Install [Terraform - 1.7.3](https://developer.hashicorp.com/terraform/tutorials/aws-get-started/install-cli)
* Install [Azure CLI - 2.57.0](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli-linux?pivots=apt)
* Install [jq - 1.6-2.1ubuntu3](https://stedolan.github.io/jq/download/)

### Generate SSH public and Private key using SSH-Keygen

```bash
CLOUD=azure
ssh_key_path=$(pwd)/modules/terraform/$CLOUD/private_key.pem
ssh-keygen -t rsa -b 2048 -f $ssh_key_path -N ""
SSH_PUBLIC_KEY_PATH="${ssh_key_path}.pub"
```

### Define Variables
Set environment variables for testing
```bash
SCENARIO_TYPE=issue-repro
SCENARIO_NAME=websocket-time-out-error
RUN_ID=$(whoami)
OWNER=$(whoami)
RESULT_PATH=/tmp/$RUN_ID
CLOUD=azure
REGIONS='["eastus"]'
MACHINE_TYPE=Standard_D2s_v5
ACCERLATED_NETWORKING=true
INGRESS_ROLE=ingress
CLIENT_NAME=client-vm
TERRAFORM_MODULES_DIR=modules/terraform/$CLOUD
SCRIPT_MODULES_DIR=modules/bash
USER_DATA_PATH=$(pwd)/scenarios/$SCENARIO_TYPE/$SCENARIO_NAME/bash-scripts
TERRAFORM_INPUT_FILE=$(pwd)/scenarios/$SCENARIO_TYPE/$SCENARIO_NAME/terraform-inputs/$CLOUD.tfvars
```
**Note**:

* `RUN_ID` should be a unique identifier since it is used to name the resource group in Azure.
* `REGIONS` contains list of regions. Multiple values are provided in case of multi-region scenario.

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
REGION=$(echo $REGIONS | jq -r '.[]')
az group create --name $RUN_ID --location $REGION --tags "run_id=$RUN_ID" "scenario=${SCENARIO_TYPE}-${SCENARIO_NAME}" "owner=azure_devops" "creation_date=$(date -u +'%Y-%m-%dT%H:%M:%SZ')" "deletion_due_time=$(date -u -d '+2 hour' +'%Y-%m-%dT%H:%M:%SZ')"
```

Set Input File

```bash
regional_config=$(jq -n '{}')
multi_region=$(echo "$REGIONS" | jq -r 'if length > 1 then "true" else "false" end')
for region in $(echo "$REGIONS" | jq -r '.[]'); do
  if [ $multi_region = "false" ]; then
    terraform_input_file=$(pwd)/scenarios/$SCENARIO_TYPE/$SCENARIO_NAME/terraform-inputs/${CLOUD}.tfvars
  else
    terraform_input_file=$(pwd)/scenarios/$SCENARIO_TYPE/$SCENARIO_NAME/terraform-inputs/${CLOUD}-${region}.tfvars
  fi
  regional_config=$(echo $regional_config | jq --arg region $region --arg file_path $terraform_input_file '. + {($region): {"TERRAFORM_INPUT_FILE" : $file_path}}')
done
regional_config_str=$(echo $regional_config | jq -c .)
```
Setup Json input for terraform:

```bash
for REGION in $(echo "$REGIONS" | jq -r '.[]'); do
  echo "Set input Json for region $REGION"
  INPUT_JSON=$(jq -n \
  --arg owner $OWNER \
  --arg run_id $RUN_ID \
  --arg region $REGION \
  --arg machine_type "$MACHINE_TYPE" \
  --arg public_key_path $SSH_PUBLIC_KEY_PATH \
  --arg accelerated_networking "$ACCELERATED_NETWORKING" \
  --arg user_data_path $TERRAFORM_USER_DATA_PATH 
  '{
    owner: $owner,
    run_id: $run_id,
    region: $region,
    machine_type: $machine_type,
    public_key_path: $public_key_path, 
    accelerated_networking: $accelerated_networking,
    user_data_path: $user_data_path
  }' | jq 'with_entries(select(.value != null and .value != ""))')
  input_json_str=$(echo $INPUT_JSON | jq -c .)
  regional_config=$(echo "$regional_config" | jq --arg region "$REGION" --arg input_variable "$input_json_str" \
    '.[$region].TERRAFORM_INPUT_VARIABLES += $input_variable')
  INPUT_JSON=""
done
```

**Note**: The `jq` command will remove any null or empty values from the JSON object. So any variable surrounded by double quotes means it is optional and can be removed if not needed.

Provision resources using Terraform:

```bash
pushd $TERRAFORM_MODULES_DIR
terraform init
for region in $(echo "$REGIONS" | jq -r '.[]'); do
  if terraform workspace list | grep -q "$region"; then
    terraform workspace select $region
  else
    terraform workspace new $region
    terraform workspace select $region
  fi
  terraform_input_file=$(echo $regional_config | jq -r --arg region "$region" '.[$region].TERRAFORM_INPUT_FILE')
  terraform_input_variables=$(echo $regional_config | jq -r --arg region "$region" '.[$region].TERRAFORM_INPUT_VARIABLES')
  
  terraform plan -var-file $terraform_input_file -var json_input=$terraform_input_variables
  
  # Check if the plan was successful
  if [ $? -ne 0 ]; then
    echo "Terraform plan failed for $region. Skipping apply."
    continue
  fi
  
  terraform apply -var-file $terraform_input_file -var json_input=$terraform_input_variables --auto-approve
done
popd
```

Once resources are provisioned, make sure to go to Azure portal to verify the resources are created as expected.

### Validate Resources
Validate Standard Load Balancer (SLB) is running and ready for traffic
```
SLB_ID=$(az resource list --resource-type Microsoft.Network/loadBalancers --query "[?(tags.run_id == '${RUN_ID}' && tags.role == '$INGRESS_ROLE')].id" --output tsv)
SLB_PIP_ID=$(az network lb show --ids $SLB_ID --query frontendIPConfigurations[0].publicIPAddress.id --output tsv)
SLB_PUBLIC_IP=$(az network public-ip show --ids $SLB_PIP_ID --query ipAddress -o tsv)
```

### Execute Tests
Run client and simulate multiple TCP connections with WebSocket protocol through Azure standard load balancer
```
az vm run-command create --name dockerCommand -g ${RUN_ID} --vm-name ${CLIENT_NAME} --async-execution true --script "docker run -e SERVER_ADDRESS=${SLB_PUBLIC_IP}" telescope.azurecr.io/issue-repro/websocket-server:v1.1.9
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
    "script": "docker run -e SERVER_ADDRESS=40.68.161.134 telescope.azurecr.io/issue-repro/websocket-server:v1.1.9",
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
{
  "endTime": "2024-05-14T00:15:37+00:00",
  "error": "",
  "executionMessage": "Execution' 'completed",
  "executionState": "Succeeded",
  "exitCode": 0,
  "output": "{\n' '\"websocket_duration_map\":' '\"{\\\"240\\\":10000}\",\n' '\"premature_closure_count\":' '\"0\",\n' '\"server_address\":' '\"40.68.161.134\",\n' '\"server_port\":' '\"443\",\n' '\"total_connections\":' '\"10000\",\n' '\"parallel_connections\":' '\"500\",\n' '\"client_timeout\":' '\"240\"\n}\n",
  "startTime": "2024-05-13T22:55:33+00:00",
  "statuses": null
}
```
if executionState field is succeeded, check output field for test results

### Cleanup Resources
Once your test is done, you can destroy the resources using Terraform.

```bash
pushd $TERRAFORM_MODULES_DIR
for region in $(echo "$REGIONS" | jq -r '.[]'); do
  if terraform workspace list | grep -q "$region"; then
    terraform workspace select $region
  else
    terraform workspace new $region
    terraform workspace select $region
  fi
  terraform_input_file=$(echo $regional_config | jq -r --arg region "$region" '.[$region].TERRAFORM_INPUT_FILE')
  terraform_input_variables=$(echo $regional_config | jq -r --arg region "$region" '.[$region].TERRAFORM_INPUT_VARIABLES')
  terraform destroy -var-file $terraform_input_file -var json_input=$terraform_input_variables --auto-approve
done
popd
```

After terraform destroys all the resources delete resource group manually.

```bash
az group delete --name $RUN_ID
```

## References

* [Azure Portal](https://portal.azure.com/)
