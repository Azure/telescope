# Azure AzAPI Module

This module creates AKS clusters via the Azure REST API using the [AzAPI Terraform provider](https://registry.terraform.io/providers/Azure/azapi/latest/docs). This enables access to preview API versions and properties not yet available in the AzureRM provider (e.g., `controlPlaneScalingProfile`).

## Usage

```hcl
module "azapi" {
  source = "./modules/terraform/azure/azapi"

  resource_group_name = var.resource_group_name
  location            = var.location
  tags                = var.tags

  azapi_config = {
    role        = "client"
    aks_name    = "my-aks-cluster"
    dns_prefix  = "my-aks"
    api_version = "2026-01-02-preview"

    sku = {
      name = "Base"
      tier = "Standard"
    }

    kubernetes_version = "1.33.0"

    network_profile = {
      network_plugin      = "azure"
      network_plugin_mode = "overlay"
    }

    default_node_pool = {
      name    = "nodepool1"
      count   = 3
      vm_size = "Standard_DS2_v2"
      os_type = "Linux"
      mode    = "System"
    }

    control_plane_scaling_profile = {
      scaling_size = "H2"
    }
  }
}
```
