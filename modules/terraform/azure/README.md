# Overview

This guide covers how to manually run Terraform for Azure. All commands should be run from the root of the repository and in a bash shell (Linux or WSL).

## Prerequisite

* Install [Terraform - 1.7.3](https://developer.hashicorp.com/terraform/tutorials/azure-get-started/install-cli)
* Install [Azure CLI - 2.57.0](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli-linux?pivots=apt)
* Install [jq - 1.6-2.1ubuntu3](https://stedolan.github.io/jq/download/)


## Define Variables

Set environment variables for a specific test scenario. In this guide, we'll use `perf-eval/apiserver-vn10pod100` scenario as the example and set the following variables:

Run the following commands from the root of the repository:
```bash
SCENARIO_TYPE=perf-eval
SCENARIO_NAME=job-scheduling
OWNER=$(whoami)
RUN_ID=$(date +%s)
CLOUD=azure
REGION=eastus2
SKU_TIER=standard
KUBERNETES_VERSION=1.33
NETWORK_POLICY=cilium
NETWORK_DATAPLANE=cilium
TERRAFORM_MODULES_DIR=modules/terraform/$CLOUD
TERRAFORM_INPUT_FILE=$(pwd)/scenarios/$SCENARIO_TYPE/$SCENARIO_NAME/terraform-inputs/${CLOUD}.tfvars
SYSTEM_NODE_POOL=${SYSTEM_NODE_POOL:-null}
USER_NODE_POOL=${USER_NODE_POOL:-null}
```

**Note**:

* `RUN_ID` should be a unique identifier since it is used to name the resource group in Azure.
* These variables are not exhaustive and may vary depending on the scenario.

### Provision Resources

Login with web browser access

```bash
az login
```

Set subscription for testing

```bash
az account set --subscription <subscriptionId>
export ARM_SUBSCRIPTION_ID=$(az account show --query id -o tsv)
```

Create Resource Group for testing

```bash
az group create --name $RUN_ID --location $REGION --tags "run_id=$RUN_ID" "scenario=${SCENARIO_TYPE}-${SCENARIO_NAME}" "owner=${OWNER}" "creation_date=$(date -u +'%Y-%m-%dT%H:%M:%SZ')" "deletion_due_time=$(date -u -d '+2 hour' +'%Y-%m-%dT%H:%M:%SZ')"
```

Set `INPUT_JSON` variable. This variable is not exhaustive and may vary depending on the scenario. For a full list of what can be set, look for `json_input` in file [`modules/terraform/azure/variables.tf`](../../../modules/terraform/azure/variables.tf) as the list will keep changing as we add more features.

```bash
  INPUT_JSON=$(jq -n \
  --arg run_id $RUN_ID \
  --arg region $REGION \
  --arg aks_sku_tier "$SKU_TIER" \
  --arg aks_kubernetes_version "$KUBERNETES_VERSION" \
  --arg aks_network_policy "$NETWORK_POLICY" \
  --arg aks_network_dataplane "$NETWORK_DATAPLANE" \
  --arg k8s_machine_type "$K8S_MACHINE_TYPE" \
  --arg k8s_os_disk_type "$K8S_OS_DISK_TYPE" \
  --argjson aks_cli_system_node_pool "$SYSTEM_NODE_POOL" \
  --argjson aks_cli_user_node_pool "$USER_NODE_POOL" \
  '{
    run_id: $run_id,
    region: $region,
    aks_sku_tier: $aks_sku_tier,
    aks_kubernetes_version: $aks_kubernetes_version,
    aks_network_policy: $aks_network_policy,
    aks_network_dataplane: $aks_network_dataplane,
    k8s_machine_type: $k8s_machine_type,
    k8s_os_disk_type: $k8s_os_disk_type,
    aks_cli_system_node_pool: $aks_cli_system_node_pool,
    aks_cli_user_node_pool: $aks_cli_user_node_pool
  }' | jq 'with_entries(select(.value != null and .value != ""))')
```

**Note**: The `jq` command will remove any null or empty values from the JSON object. So any variable surrounded by double quotes means it is optional and can be removed if not needed.

### Provision resources using Terraform:
```bash
pushd $TERRAFORM_MODULES_DIR
terraform init
terraform plan -var json_input=$(echo $INPUT_JSON | jq -c .) -var-file $TERRAFORM_INPUT_FILE
terraform apply -var json_input=$(echo $INPUT_JSON | jq -c .) -var-file $TERRAFORM_INPUT_FILE
popd
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
az group delete --name $RUN_ID -y
```

## References

* [Terraform Azure Provider](https://registry.terraform.io/providers/hashicorp/azurerm/latest/docs)
* [Azure CLI](https://learn.microsoft.com/en-us/cli/azure/reference-index?view=azure-cli-latest)
* [Azure Service Principle](https://docs.microsoft.com/en-us/cli/azure/create-an-azure-service-principal-azure-cli?view=azure-cli-latest)
* [Azure Portal](https://portal.azure.com/)
