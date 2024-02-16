## Overview

This guide covers how to manually run Terraform for Azure. All commands should be run from the root of the repository and in a bash shell (Linux or WSL).

### Prerequisite

* Install Terraform (https://developer.hashicorp.com/terraform/tutorials/aws-get-started/install-cli)
* Install Azure CLI (https://learn.microsoft.com/en-us/cli/azure/install-azure-cli-linux?pivots=apt)

### Define Variables

Set environment variables for a specific test scenario. In this guide, we'll use `perf-eval/vm-same-zone-iperf` scenario as the example and set the following variables:

```
SCENARIO_TYPE=perf-eval
SCENARIO_NAME=vm-same-zone-iperf
RUN_ID=123456789
OWNER=$(whoami)
CLOUD=azure
REGION=eastus
MACHINE_TYPE=standard_D16_v3
ACCERLATED_NETWORKING=true
TERRAFORM_MODULES_DIR=modules/terraform/$CLOUD
USER_DATA_PATH=$(pwd)/scenarios/$SCENARIO_TYPE/$SCENARIO_NAME/bash-scripts
TERRAFORM_INPUT_FILE=$(pwd)/scenarios/$SCENARIO_TYPE/$SCENARIO_NAME/terraform-inputs/$CLOUD.tfvars
```

**Note**:
* `RUN_ID` should be a unique identifier since it's used to name the resource group.
* These variables are not exhaustive and may vary depending on the scenario.

### Provision Resources

Login with web browser access
```
az login
```

Login without web browser like from a Linux devbox or VM, please create a service principle first to login with the service principle
```
az ad sp create-for-rbac --name <servicePrincipleName> --role contributor --scopes /subscriptions/<subscriptionId>
{
  "appId": "xxx",
  "displayName": "xxx",
  "password": "xxx",
  "tenant": "xxx"
}

az login --service-principal --username <appId> --password <password> --tenant <tenant>
```

Set subscription for testing
```
az account set --subscription <subscriptionId>
```

Provision resources using Terraform. Again, this `INPUT_JSON` is not exhaustive and may vary depending on the scenario. For a full list of what can be set, look for `json_input` in file `modules/terraform/azure/variables.tf`

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

Once resources are provisioned, make sure to go to Azure portal to verify the resources are created as expected.

### Cleanup Resources

Once your test is done, you can destroy the resources using Terraform.
```
pushd $TERRAFORM_MODULES_DIR
terraform destroy -var json_input=$(echo $INPUT_JSON | jq -c .) -var-file $TERRAFORM_INPUT_FILE
popd
```
