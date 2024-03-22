# Azure Kubernetes Service (AKS) Module

This module provisions an Azure Kubernetes Service (AKS) cluster. It allows you to create and configure a managed Kubernetes cluster with customizable settings.

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

### `subnet_id`

- **Description:** ID of the subnet where the AKS cluster will be deployed.
- **Type:** String
- **Default:** ""

### `vm_sku`

- **Description:** SKU (Stock Keeping Unit) of the virtual machines used in the AKS cluster.
- **Type:** String
- **Default:** "Standard_D2ds_v5"

### `vnet_id`

- **Description:** ID of the virtual network where the AKS cluster will be deployed.
- **Type:** String
- **Default:** ""

### `aks_config`

- **Description:** Configuration for the AKS cluster.
- **Type:** Object
  - `role`: Role of the AKS cluster
  - `aks_name`: Name of the AKS cluster
  - `dns_prefix`: DNS prefix for the AKS cluster
  - `subnet_name`: Name of the subnet
  - `network_plugin`: Network plugin used by the AKS cluster
  - `default_node_pool`: Configuration for the default node pool
  - `extra_node_pool`: Additional node pools for the AKS cluster
    - `name`: Name of the node pool
    - `node_count`: Number of nodes in the node pool

## Usage Example

```hcl
module "aks" {
  source = "./aks"

  resource_group_name = "my-rg"
  location            = "West Europe"
  subnet_id           = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/my-rg/providers/Microsoft.Network/virtualNetworks/my-vnet/subnets/my-subnet"
  vm_sku              = "Standard_D2s_v3"
  vnet_id             = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/my-rg/providers/Microsoft.Network/virtualNetworks/my-vnet"
  aks_config = {
    role            = "dev"
    aks_name        = "my-aks-cluster"
    dns_prefix      = "myaksdns"
    subnet_name     = "my-subnet"
    network_plugin  = "kubenet"
    default_node_pool = {
      name                         = "default-pool"
      node_count                   = 3
      os_disk_type                 = "Ephemeral"
      only_critical_addons_enabled = false
      temporary_name_for_rotation  = "true"
    }
    extra_node_pool = [
      {
        name       = "pool-1"
        node_count = 2
      },
      {
        name       = "pool-2"
        node_count = 2
      }
    ]
  }

  tags = {
    environment = "production"
    project     = "example"
  }
}
```