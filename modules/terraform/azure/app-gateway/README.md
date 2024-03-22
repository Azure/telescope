# Application Gateway Module

This module provisions an Application Gateway in Azure. It allows you to create and configure an Application Gateway with customizable settings.

## Input Variables

### `resource_group_name`

- **Description:** Name of the resource group where the Application Gateway will be created.
- **Type:** String
- **Default:** "rg"

### `location`

- **Description:** Azure region where the Application Gateway will be deployed.
- **Type:** String
- **Default:** "East US"

### `tags`

- **Description:** Tags to apply to the Application Gateway resources.
- **Type:** Map of strings
- **Default:** None

### `subnet_id`

- **Description:** ID of the subnet where the Application Gateway will be deployed.
- **Type:** String
- **Default:** ""

### `appgateway_config`

- **Description:** Configuration for the Application Gateway.
- **Type:** Object
  - `role`: Role of the Application Gateway
  - `appgateway_name`: Name of the Application Gateway
  - `public_ip_name`: Name of the associated public IP
  - `subnet_name`: Name of the subnet
  - `appgateway_probes`: List of health probes
  - `appgateway_backend_address_pool`: List of backend address pools
  - `appgateway_frontendport`: Frontend port configuration
  - `appgateway_backend_http_settings`: List of backend HTTP settings
  - `appgateway_http_listeners`: List of HTTP listeners
  - `appgateway_request_routing_rules`: List of request routing rules
- **Default:** None

### `public_ip_id`

- **Description:** ID of the public IP associated with the Application Gateway (if applicable).
- **Type:** String
- **Default:** null

## Usage Example

```hcl
module "app_gateway" {
  source = "./app-gateway"

  resource_group_name = "my-rg"
  location            = "West Europe"
  subnet_id           = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/my-rg/providers/Microsoft.Network/virtualNetworks/my-vnet/subnets/my-subnet"
  appgateway_config   = {
    role                        = "web"
    appgateway_name             = "my-app-gateway"
    public_ip_name              = "my-public-ip"
    subnet_name                 = "my-subnet"
    appgateway_probes           = [
      {
        name     = "http-probe"
        protocol = "Http"
      }
    ]
    appgateway_backend_address_pool = [
      {
        name         = "backend-pool"
        ip_addresses = ["10.0.1.10", "10.0.1.11"]
      }
    ]
    appgateway_frontendport = {
      name = "my-frontend-port"
      port = "80"
    }
    appgateway_backend_http_settings = [
      {
        name                  = "http-settings"
        host_name             = "example.com"
        cookie_based_affinity = "Disabled"
        port                  = 8080
        protocol              = "Http"
        request_timeout       = 30
        probe_name            = "http-probe"
      }
    ]
    appgateway_http_listeners = [
      {
        name                           = "http-listener"
        frontend_ip_configuration_name = "my-frontend-ip"
        frontend_port_name             = "my-frontend-port"
        protocol                       = "Http"
        host_name                      = "example.com"
      }
    ]
    appgateway_request_routing_rules = [
      {
        name                       = "routing-rule"
        priority                   = 1
        rule_type                  = "Basic"
        http_listener_name         = "http-listener"
        backend_address_pool_name  = "backend-pool"
        backend_http_settings_name = "http-settings"
      }
    ]
  }
  public_ip_id        = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/my-rg/providers/Microsoft.Network/publicIPAddresses/my-public-ip"

  tags = {
    environment = "production"
    project     = "example"
  }
}
```