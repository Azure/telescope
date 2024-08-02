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
  - `aks_custom_headers`: Custom headers for AKS.
  - `use_aks_preview_cli_extension`: using aks-preview cli extension
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

  location            = "West Europe"

  tags = {
    environment = "production"
    project     = "example"
  }

  aks_cli_config = {
    role     = "dev"
    aks_name = "my-aks-cluster"
    sku_tier = "standard"

    use_aks_preview_cli_extension = true

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
        name       = "pool-1"
        node_count = 2
        vm_size    = "Standard_D2s_v3"
        vm_set_type = "VirtualMachines"
      },
      {
        name       = "pool-2"
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
2. Generate SSH public and Private key using SSH-Keygen

```bash
CLOUD=azure
ssh_key_path=$(pwd)/modules/terraform/$CLOUD/private_key.pem
ssh-keygen -t rsa -b 2048 -f $ssh_key_path -N ""
SSH_PUBLIC_KEY_PATH="${ssh_key_path}.pub"
```
3. set environment vars with your own scenario name, 
```bash
SCENARIO_TYPE=perf-eval
SCENARIO_NAME=k8s-cluster-crud
RUN_ID=08022024
OWNER=$(whoami)
RESULT_PATH=/tmp/$RUN_ID
CLOUD=azure
REGION=eastus
MACHINE_TYPE=standard_D4_v3
TERRAFORM_MODULES_DIR=modules/terraform/$CLOUD
TEST_MODULES_DIR=modules/bash
TERRAFORM_INPUT_FILE=$(pwd)/scenarios/$SCENARIO_TYPE/$SCENARIO_NAME/terraform-inputs/${CLOUD}.tfvars
DEFAULT_NODE_POOL="{\"name\":\"default\",\"vm_size\":\"Standard_D2s_v3\",\"node_count\":1,\"vm_set_type\":\"VirtualMachineScaleSets\"}"
EXTRA_NODE_POOL="[{\"name\":\"pool1\",\"vm_size\":\"Standard_D2s_v3\",\"node_count\":1,\"vm_set_type\":\"VirtualMachineScaleSets\"},{\"name\":\"pool2\",\"vm_size\":\"Standard_D2s_v3\",\"node_count\":1,\"vm_set_type\":\"VirtualMachineScaleSets\"}]"
```
1. az login with your sub
1. run following command to apply terraform config
```bash
INPUT_JSON=$(jq -n \
--arg owner $OWNER \
--arg run_id $RUN_ID \
--arg region $REGION \
--arg machine_type $MACHINE_TYPE \
--argjson aks_cli_default_node_pool $DEFAULT_NODE_POOL \
--argjson aks_cli_extra_node_pool $EXTRA_NODE_POOL \
--arg public_key_path "$SSH_PUBLIC_KEY_PATH" \
'{owner: $owner, run_id: $run_id, region: $region, machine_type: $machine_type, public_key_path: $public_key_path, aks_cli_default_node_pool: $aks_cli_default_node_pool, aks_cli_extra_node_pool: $aks_cli_extra_node_pool}'| jq 'with_entries(select(.value != null and .value != ""))')
```

pushd $TERRAFORM_MODULES_DIR
terraform init
terraform apply -var json_input=$(echo $INPUT_JSON | jq -c .) -var-file $TERRAFORM_INPUT_FILE
popd
### Cleanup Resources
Cleanup test resources using terraform
```
pushd $TERRAFORM_MODULES_DIR
terraform destroy -var json_input=$(echo $INPUT_JSON | jq -c .) -var-file $TERRAFORM_INPUT_FILE
popd
```