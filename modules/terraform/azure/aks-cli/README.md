# Azure Kubernetes Service (AKS) CLI Module

This module provisions an Azure Kubernetes Service (AKS) cluster by command
line. It can be considered when `azurerm_kubernetes_cluster` doesn't support
configuration, like `--aks-custom-headers" flags. It also supports to use aks-preview cli extension

## Input Variables

### `resource_group_name`

- **Description:** Name of the resource group where the AKS cluster will be created.
- **Type:** String
- **Default:** "rg"

### `location`

- **Description:** Azure region where the AKS cluster will be deployed.
- **Type:** String
- **Default:** "East US"

### `tags`

- **Description:** Tags to apply to the AKS resources.
- **Type:** Map of strings
- **Default:** None

### `aks_cli_config`

- **Description:** Configuration for the AKS cluster.
- **Type:** Object
  - `role`: Role of the AKS cluster
  - `aks_name`: Name of the AKS cluster
  - `sku_tier`: The type of pricing tiers
  - `kubernetes_version`: The kubernetes version of the AKS cluster
  - `aks_custom_headers`: Custom headers for AKS.
  - `use_aks_preview_cli_extension`: using aks-preview cli extension
  - `use_aks_preview_private_build`: using aks-preview private build
  - `default_node_pool`: Configuration for the default node pool
  - `extra_node_pool`: Additional node pools for the AKS cluster
    - `name`: Name of the node pool
    - `node_count`: Number of nodes in the node pool
    - `vm_size`: Size of Virtual Machines to create as Kubernetes nodes.
    - `vm_set_type`: agent pool type, default value is "VirtualMachineScaleSets"

## Usage Example

```hcl
module "aks" {
  source = "./aks-cli"

  resource_group_name = "my-rg"

  location            = "eastus"

  tags = {
    environment = "production"
    project     = "example"
  }

  aks_cli_config = {
    role     = "dev"
    aks_name = "my-aks-cluster"
    sku_tier = "standard"
    kubernetes_version = "1.31"

    use_aks_preview_cli_extension = true
    use_aks_preview_private_build = true

    aks_custom_headers = [
      "WindowsContainerRuntime=containerd",
      "AKSHTTPCustomFeatures=Microsoft.ContainerService/CustomNodeConfigPreview",
    ]

    default_node_pool = {
      name        = "default-pool"
      vm_size     = "Standard_D2s_v3"
      node_count  = 3
      vm_set_type = "VirtualMachines"
    }
    extra_node_pool = [
      {
        name       = "pool1"
        node_count = 2
        vm_size    = "Standard_D2s_v3"
        vm_set_type = "VirtualMachines"
      },
      {
        name       = "pool2"
        node_count = 2
        vm_size    = "Standard_D2s_v3"
        vm_set_type = "VirtualMachines"
      }
    ]
  }
}
```

## How to test above setting locally
1. you should have `terraform` and `azure cli` installed to your local machine
2. Login with your subscription using azure cli
3. set environment vars with your test scenario name.
```bash
SCENARIO_TYPE=perf-eval
SCENARIO_NAME=apiserver-vn100pod10k
RUN_ID=$(date +%s)
CLOUD=azure
REGION=eastus
KUBERNETES_VERSION=1.31
TERRAFORM_MODULES_DIR=modules/terraform/$CLOUD
TERRAFORM_INPUT_FILE=$(pwd)/scenarios/$SCENARIO_TYPE/$SCENARIO_NAME/terraform-inputs/${CLOUD}.tfvars
SYSTEM_NODE_POOL="{\"name\":\"default\",\"vm_size\":\"Standard_D2_v3\",\"node_count\":1,\"vm_set_type\":\"VirtualMachineScaleSets\"}"
USER_NODE_POOL="[{\"name\":\"pool1\",\"vm_size\":\"Standard_D2_v3\",\"node_count\":1,\"vm_set_type\":\"VirtualMachineScaleSets\"},{\"name\":\"pool2\",\"vm_size\":\"Standard_D2_v3\",\"node_count\":1,\"vm_set_type\":\"VirtualMachineScaleSets\"}]"
```
4. Run following command to set `INPUT_JSON` variable
```bash
INPUT_JSON=$(jq -n \
--arg run_id $RUN_ID \
--arg region $REGION \
--arg aks_kubernetes_version "$KUBERNETES_VERSION" \
--argjson aks_cli_system_node_pool $SYSTEM_NODE_POOL \
--argjson aks_cli_user_node_pool $USER_NODE_POOL \
'{
    run_id: $run_id, 
    region: $region,
    aks_kubernetes_version: $aks_kubernetes_version,
    aks_cli_system_node_pool: $aks_cli_system_node_pool, 
    aks_cli_user_node_pool: $aks_cli_user_node_pool
}'| jq 'with_entries(select(.value != null and .value != ""))')
```
5. Run terraform provisioning commands from [here](./../README.md#provision-resources-using-terraform)