# Application Load Balancer Module

This module provisions an Application Gateway for Containers and ALB Controller on an AKS cluster.

## Input Variables

### `resource_group_name`

- **Description:** Name of the resource group where the AGC resource will be deployed
- **Type:** String
- **Default:** "rg"

### `location`

- **Description:** Azure region where the AGC resource will be deployed
- **Type:** String
- **Default:** "East US"

### `tags`

- **Description:** Tags to apply to the AGC resource.
- **Type:** Map of strings
- **Default:** None

### `aks_cluster_oidc_issuer`

- **Description:** OIDC issuer of the cluster where ALB Controller will be deployed.
- **Type:** String
- **Default:** ""

### `association_subnet_id`

- **Description:** ID of the subnet where association will be deployed
- **Type:** String
- **Default:** ""

### `agc_config`

- **Description:** Configuration for the AGC resource.
- **Type:** Object
  - `role`: Role of the AGC resource
  - `name`: Name of the AGC resource
  - `frontends`: List of frontend names to create in AGC resource.
  - `association_subnet_name`: Name of the subnet where association will be deployed.

## Usage Example

```hcl
module "agc" {
  source = "./agc"

  resource_group_name = "my-rg"
  location            = "West Europe"
  tags = {
    environment = "production"
    project     = "example"
  }
  aks_cluster_oidc_issuer = "https://westeurope.oic.prod-aks.azure.com/00000000-0000-0000-0000-000000000000/00000000-0000-0000-0000-000000000000/"
  association_subnet_id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/my-rg/providers/Microsoft.Network/virtualNetworks/my-vnet/subnets/my-subnet"
  
  agc_config = {
    role                    = "dev"
    name                    = "my-agc"
    frontends               = ["frontend-1", "frontend-2"]
    association_subnet_name = "my-subnet"
  }
}
```

## Terraform Provider References

### Resources

- [azurerm_kubernetes_cluster Documentation](https://registry.terraform.io/providers/hashicorp/azurerm/latest/docs/resources/kubernetes_cluster)
- [azurerm_kubernetes_cluster_node_pool Documentation](https://registry.terraform.io/providers/hashicorp/azurerm/latest/docs/resources/kubernetes_cluster_node_pool)
