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
SCENARIO_NAME=websocket-timeout-error
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
  --arg user_data_path $USER_DATA_PATH \
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

ssh -i $ssh_key_path -p 2222 ubuntu@52.168.52.247 "docker run -e SERVER_ADDRESS=${SLB_PUBLIC_IP}" telescope.azurecr.io/issue-repro/websocket-server:v1.1.9" > docker_output.log

```
Then wait for the test to finish execution

### Collect Results
Get the results stored in the log file by running command as below:
```
cat docker_output.log
{
  "websocket_duration_map": "{\"240\":500}",
  "premature_closure_count": "0",
  "server_address": "52.174.62.244",
  "server_port": "443",
  "total_connections": "500",
  "parallel_connections": "500",
  "client_timeout": "240",
  "error_log": "Connecting to wss://52.174.62.244:443/ws\n500 total connections to be established\n500 parallel connections to be established\nSet client timeout to 240 seconds\n{\"240\":500}\nTotal number of premature closures: 0"
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
