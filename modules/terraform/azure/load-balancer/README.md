# Load Balancer Module

This module provisions a load balancer in Azure. It allows you to create and configure a load balancer with customizable settings.

## Input Variables

### `resource_group_name`

- **Description:** Name of the resource group where the load balancer will be created.
- **Type:** String
- **Default:** "rg"

### `location`

- **Description:** Azure region where the load balancer will be deployed.
- **Type:** String
- **Default:** "eastus"

### `pip_id`

- **Description:** ID of the public IP associated with the load balancer.
- **Type:** String
- **Default:** ""

### `loadbalancer_config`

- **Description:** Configuration for the load balancer.
- **Type:** Object
  - `role`: Role of the load balancer
  - `loadbalance_name`: Name of the load balancer
  - `public_ip_name`: Name of the public IP
  - `loadbalance_pool_name`: Name of the load balancer pool
  - `probe_protocol`: Protocol for the health probe
  - `probe_port`: Port for the health probe
  - `probe_request_path`: Request path for the health probe
  - `lb_rules`: List of load balancing rules

### `public_ip_id`

- **Description:** ID of the public IP associated with the load balancer (if applicable).
- **Type:** String
- **Default:** null

### `is_internal_lb`

- **Description:** Indicates whether the load balancer is internal.
- **Type:** Boolean
- **Default:** false

### `subnet_id`

- **Description:** ID of the subnet where the load balancer will be deployed.
- **Type:** String
- **Default:** ""

### `tags`

- **Type:** Map of strings
- **Default:** None

## Usage Example

```hcl
module "load_balancer" {
  source = "./load-balancer"

  resource_group_name = "my-rg"
  location            = "West Europe"
  pip_id              = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/my-rg/providers/Microsoft.Network/publicIPAddresses/my-public-ip"
  loadbalancer_config = {
    role                  = "web"
    loadbalance_name      = "my-lb"
    public_ip_name        = "my-public-ip"
    loadbalance_pool_name = "my-lb-pool"
    probe_protocol        = "HTTP"
    probe_port            = 80
    probe_request_path    = "/"
    lb_rules = [
      {
        type                    = "LoadBalancingRule"
        role                    = "web-lb-rule"
        frontend_port           = 80
        backend_port            = 8080
        protocol                = "Tcp"
        rule_count              = 1
        enable_tcp_reset        = true
        idle_timeout_in_minutes = 4
      }
    ]
  }
  public_ip_id        = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/my-rg/providers/Microsoft.Network/publicIPAddresses/my-public-ip"
  is_internal_lb      = false
  subnet_id           = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/my-rg/providers/Microsoft.Network/virtualNetworks/my-vnet/subnets/my-subnet"

  tags = {
    environment = "production"
    project     = "example"
  }
}
```

# Load Balancer Module Outputs

This module provides the following outputs:

## `lb_pool_id`

- **Description:** ID of the load balancer backend address pool.
- **Type:** String

## `lb_fipc_id`

- **Description:** ID of the load balancer frontend IP configuration.
- **Type:** String

## Terraform Provider References

### Resources

- [azurerm_lb Documentation](https://registry.terraform.io/providers/hashicorp/azurerm/latest/docs/resources/lb)
- [azurerm_lb_backend_address_pool Documentation](https://registry.terraform.io/providers/hashicorp/azurerm/latest/docs/resources/lb_backend_address_pool)
- [azurerm_lb_probe Documentation](https://registry.terraform.io/providers/hashicorp/azurerm/latest/docs/resources/lb_probe)
