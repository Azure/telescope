# Load Balancer Rules Module

This module provisions load balancer rules in Azure. It allows you to create and configure load balancer rules with customizable settings.

## Input Variables

### `role`

- **Description:** Prefix for the lb-rule name.
- **Type:** String

### `type`

- **Description:** Load Balancer Rule Type.
- **Type:** String
- **Default:** "Inbound"

### `frontend_port`

- **Description:** Value for frontend_port.
- **Type:** Number

### `backend_port`

- **Description:** Value for backend_port.
- **Type:** Number

### `lb_id`

- **Description:** ID of the Azure Load Balancer.
- **Type:** String

### `lb_pool_id`

- **Description:** ID of the Azure Load Balancer Backend Address Pool.
- **Type:** String

### `probe_id`

- **Description:** ID of the Azure Load Balancer Probe.
- **Type:** String

### `protocol`

- **Description:** Value for protocol.
- **Type:** String
- **Default:** "Tcp"

### `rule_count`

- **Description:** Number of rules to create.
- **Type:** Number
- **Default:** 1

### `enable_tcp_reset`

- **Description:** Value for enable_tcp_reset.
- **Type:** Boolean
- **Default:** true

### `idle_timeout_in_minutes`

- **Description:** Value for idle_timeout_in_minutes.
- **Type:** Number
- **Default:** 4

### `frontend_ip_config_role`

- **Description:** Value for frontend_ip_configuration_name prefix.
- **Type:** String
- **Default:** "ingress"

## Usage Example

```hcl
module "load_balancer_rules" {
  source = "./lb-rule"

  role                        = "web"
  type                        = "Inbound"
  frontend_port               = 80
  backend_port                = 8080
  lb_id                       = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/my-rg/providers/Microsoft.Network/loadBalancers/my-lb"
  lb_pool_id                  = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/my-rg/providers/Microsoft.Network/loadBalancers/my-lb/backendAddressPools/my-pool"
  probe_id                    = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/my-rg/providers/Microsoft.Network/loadBalancers/my-lb/probes/my-probe"
  protocol                    = "Tcp"
  rule_count                  = 1
  enable_tcp_reset            = true
  idle_timeout_in_minutes     = 4
  frontend_ip_config_role     = "ingress"

  # Additional variables as needed
}
