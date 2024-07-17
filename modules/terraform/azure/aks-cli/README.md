# Azure Kubernetes Service (AKS) CLI Module

This module provisions an Azure Kubernetes Service (AKS) cluster by command
line. It can be considered when `azurerm_kubernetes_cluster` doesn't support
configuration, like `--aks-custom-headers" flags.

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
  - `default_node_pool`: Configuration for the default node pool
  - `extra_node_pool`: Additional node pools for the AKS cluster
    - `name`: Name of the node pool
    - `node_count`: Number of nodes in the node pool
    - `vm_size`: Size of Virtual Machines to create as Kubernetes nodes.

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

    aks_custom_headers = [
      "WindowsContainerRuntime=containerd",
      "AKSHTTPCustomFeatures=Microsoft.ContainerService/CustomNodeConfigPreview",
    ]

    default_node_pool = {
      name       = "default-pool"
      vm_size    = "Standard_D2s_v3"
      node_count = 3
    }
    extra_node_pool = [
      {
        name       = "pool-1"
        node_count = 2
        vm_size    = "Standard_D2s_v3"
      },
      {
        name       = "pool-2"
        node_count = 2
        vm_size    = "Standard_D2s_v3"
      }
    ]
  }
}
```
