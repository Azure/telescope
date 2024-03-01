## Overview

This guide covers how to manually run Terraform for Azure. All commands should be run from the root of the repository and in a bash shell (Linux or WSL).

### Prerequisite

* Install [Terraform - 1.7.3](https://developer.hashicorp.com/terraform/tutorials/azure-get-started/install-cli)
* Install [Azure CLI - 2.57.0](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli-linux?pivots=apt)
* Install [jq - 1.6-2.1ubuntu3](https://stedolan.github.io/jq/download/)

### Generate SSH public and Private key using SSH-Keygen
```
CLOUD=azure
ssh_key_path=$(pwd)/modules/terraform/$CLOUD/private_key.pem
ssh-keygen -t rsa -b 2048 -f $ssh_key_path -N ""
SSH_PUBLIC_KEY_PATH="${ssh_key_path}.pub"
```

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
TERRAFORM_USER_DATA_PATH=$(pwd)/scenarios/$SCENARIO_TYPE/$SCENARIO_NAME/bash-scripts
TERRAFORM_INPUT_FILE=$(pwd)/scenarios/$SCENARIO_TYPE/$SCENARIO_NAME/terraform-inputs/$CLOUD.tfvars
```

**Note**:
* `RUN_ID` should be a unique identifier since it is used to name the resource group in Azure.
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

Create Resource Group for testing
```
az group create --name $RUN_ID --location $REGION --tags "run_id=$RUN_ID" "scenario=${SCENARIO_TYPE}-${SCENARIO_NAME}" "owner=azure_devops" "creation_date=$(date -u +'%Y-%m-%dT%H:%M:%SZ')" "deletion_due_time=$(date -u -d '+2 hour' +'%Y-%m-%dT%H:%M:%SZ')"
```

Set `INPUT_JSON` variable. This variable is not exhaustive and may vary depending on the scenario. For a full list of what can be set, look for `json_input` in file [`modules/terraform/azure/variables.tf`](../../../modules/terraform/azure/variables.tf) as the list will keep changing as we add more features.

```
INPUT_JSON=$(jq -n \
  --arg owner $OWNER \
  --arg run_id $RUN_ID \
  --arg region $REGION \
  --arg machine_type "$MACHINE_TYPE" \
  --arg public_key_path $SSH_PUBLIC_KEY_PATH \
  --arg aks_machine_type "$AKS_MACHINE_TYPE" \
  --arg accelerated_networking "$ACCELERATED_NETWORKING" \
  --arg data_disk_storage_account_type "$DATA_DISK_TYPE" \
  --arg data_disk_size_gb "$DATA_DISK_SIZE_GB" \
  --arg data_disk_tier "$DATA_DISK_TIER" \
  --arg data_disk_caching "$DATA_DISK_CACHING" \
  --arg data_disk_iops_read_write "$DATA_DISK_IOPS_READ_WRITE" \
  --arg data_disk_iops_read_only "$DATA_DISK_IOPS_READ_ONLY" \
  --arg data_disk_mbps_read_write "$DATA_DISK_MBPS_READ_WRITE" \
  --arg data_disk_mbps_read_only "$DATA_DISK_MBPS_READ_ONLY" \
  --arg ultra_ssd_enabled "$ULTRA_SSD_ENABLED" \
  --arg storage_account_tier "$STORAGE_TIER" \
  --arg storage_account_kind "$STORAGE_KIND" \
  --arg storage_account_replication_type "$STORAGE_REPLICATION" \
  --arg storage_share_quota "$STORAGE_SHARE_QUOTA" \
  --arg storage_share_access_tier "$STORAGE_SHARE_ACCESS_TIER" \
  --arg storage_share_enabled_protocol "$STORAGE_SHARE_ENABLED_PROTOCOL" \
  --arg user_data_path $TERRAFORM_USER_DATA_PATH \
  '{
    owner: $owner,
    run_id: $run_id,
    region: $region,
    machine_type: $machine_type,
    public_key_path: $public_key_path, 
    aks_machine_type: $aks_machine_type,
    accelerated_networking: $accelerated_networking,
    data_disk_storage_account_type: $data_disk_storage_account_type,
    data_disk_size_gb: $data_disk_size_gb,
    data_disk_tier: $data_disk_tier,
    data_disk_caching: $data_disk_caching,
    data_disk_iops_read_write: $data_disk_iops_read_write,
    data_disk_iops_read_only: $data_disk_iops_read_only,
    data_disk_mbps_read_write: $data_disk_mbps_read_write,
    data_disk_mbps_read_only: $data_disk_mbps_read_only,
    ultra_ssd_enabled: $ultra_ssd_enabled,
    storage_account_tier: $storage_account_tier,
    storage_account_kind: $storage_account_kind,
    storage_account_replication_type: $storage_account_replication_type,
    storage_share_quota: $storage_share_quota,
    storage_share_access_tier: $storage_share_access_tier,
    storage_share_enabled_protocol: $storage_share_enabled_protocol,
    user_data_path: $user_data_path
  }' | jq 'with_entries(select(.value != null and .value != ""))')
```

**Note**: The `jq` command will remove any null or empty values from the JSON object. So any variable surrounded by double quotes means it is optional and can be removed if not needed.

Provision resources using Terraform:

```
pushd $TERRAFORM_MODULES_DIR
terraform init
terraform plan -var json_input=$(echo $INPUT_JSON | jq -c .) -var-file $TERRAFORM_INPUT_FILE
terraform apply -var json_input=$(echo $INPUT_JSON | jq -c .) -var-file $TERRAFORM_INPUT_FILE --auto-approve
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
After terraformn destroys all the resources delete resource group manually.
```
az group delete --name $RUN_ID
```

### References
* [Terraform Azure Provider](https://registry.terraform.io/providers/hashicorp/azurerm/latest/docs)
* [Azure CLI](https://learn.microsoft.com/en-us/cli/azure/reference-index?view=azure-cli-latest)
* [Azure Service Principle](https://docs.microsoft.com/en-us/cli/azure/create-an-azure-service-principal-azure-cli?view=azure-cli-latest)
* [Azure Portal](https://portal.azure.com/)
