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

### `pod_ip_allocation_mode`

- **Description:** The IP allocation mode for pods in the agent pool. Possible values **DynamicIndividual** or **StaticBlock**
- **Type:** String
- **Default:** "DynamicIndividual"
  
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
  - `sku_tier`: The type of pricing tiers
  - `network_profile `: Network profile for the AKS cluster
    - `network_plugin`: Network plugin used by the AKS cluster
    - `network_policy`: Network policy used by the AKS cluster
    - `outbound_type`: Outbound type used by the AKS cluster
    - `pod_cidr`: Pod cidr used by the AKS cluster
    - `ebpf_data_plane`: Data plane used by the AKS cluster, default `azure`
  - `service_mesh_profile`: Istio addon profile
    - `mode`: Enable addon by setting to "Istio"
  - `default_node_pool`: Configuration for the default node pool
  - `extra_node_pool`: Additional node pools for the AKS cluster
    - `name`: Name of the node pool
    - `node_count`: Number of nodes in the node pool
    - `vm_size`: Size of Virtual Machines to create as Kubernetes nodes.
    - `max_pods`: Maximum pods per node on the node pool.
    - `zones`: Zones of the node pool

### `k8s_machine_type` (optional)

- **Description:** The optional field `k8s_machine_type` overrides, when set, the vm_size of all AKS nodes defined in `aks_config`. This is useful to define scenarios with different instance types using the same base config. Valid values can be found in the [Azure VM sizes documentation](https://docs.microsoft.com/en-us/azure/virtual-machines/sizes).
- **Type:** String
- **Default:** null

## Usage Example

```hcl
module "aks" {
  source = "./aks"

  resource_group_name = "my-rg"
  location            = "West Europe"
  subnet_id           = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/my-rg/providers/Microsoft.Network/virtualNetworks/my-vnet/subnets/my-subnet"
  vnet_id             = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/my-rg/providers/Microsoft.Network/virtualNetworks/my-vnet"
  aks_config = {
    role            = "dev"
    aks_name        = "my-aks-cluster"
    dns_prefix      = "myaksdns"
    subnet_name     = "my-subnet"
    network_profile = {
      network_plugin = "kubenet"
      pod_cidr       = "125.4.0.0/14"
    }
    default_node_pool = {
      name                         = "default-pool"
      vm_size                      = "Standard_D2s_v3"
      node_count                   = 3
      os_disk_type                 = "Ephemeral"
      only_critical_addons_enabled = false
      temporary_name_for_rotation  = "true"
      max_pods                     = 3
    }
    extra_node_pool = [
      {
        name       = "pool-1"
        node_count = 2
        vm_size    = "Standard_D2s_v3"
        max_pods   = 3
      },
      {
        name       = "pool-2"
        node_count = 2
        vm_size    = "Standard_D2s_v3"
        max_pods   = 3
      }
    ]
  }

  tags = {
    environment = "production"
    project     = "example"
  }
}
```

## Terraform Provider References

### Resources

- [azurerm_kubernetes_cluster Documentation](https://registry.terraform.io/providers/hashicorp/azurerm/latest/docs/resources/kubernetes_cluster)
- [azurerm_kubernetes_cluster_node_pool Documentation](https://registry.terraform.io/providers/hashicorp/azurerm/latest/docs/resources/kubernetes_cluster_node_pool)
