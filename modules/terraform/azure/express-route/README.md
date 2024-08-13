This module provisions express routes in Azure 
## Express Route Circuit - Physical connection linking on prem network to Azure 

### `resource_group_name`

- **Description:** Name of the resource group where the proximity group will be created.
- **Type:** String
- **Default:** "rg"

### `location`

- **Description:** Azure region where the proximity group will be deployed.
- **Type:** String
- **Default:** "eastus"

### `name`

- **Description:** Name of the express route circuit.
- **Type:** String
- **Default:** ""

### `service_provider_name`

- **Description:** Name of the service provider for the express route circuit.
- **Type:** String
- **Default:** ""

### `peering_location`

- **Description:** Name of the peering location for the express route circuit.
- **Type:** String
- **Default:** ""

### `bandwidth_in_mbps`

- **Description:** Bandwidth of the express route circuit.
- **Type:** Integer
- **Default:** ""

### `tags`

- **Type:** Map of strings
- **Default:** {}

## Virtual Network Gateway - Manages a Virtual Network Gateway to establish a securet cross-premises connectivity. Need one for each Virtual Network involved 

### `resource_group_name`

- **Description:** Name of the resource group where the proximity group will be created.
- **Type:** String
- **Default:** "rg"

### `location`

- **Description:** Azure region where the proximity group will be deployed.
- **Type:** String
- **Default:** "eastus"

### `name`

- **Description:** Name of the express route circuit.
- **Type:** String
- **Default:** ""

### `tags`

- **Type:** Map of strings
- **Default:** {}

## Virtual Network Gateway Connection - Connects the Virtual Network Gateway to the Public IP

### `resource_group_name`

- **Description:** Name of the resource group where the proximity group will be created.
- **Type:** String
- **Default:** "rg"

### `location`

- **Description:** Azure region where the proximity group will be deployed.
- **Type:** String
- **Default:** "eastus"

### `name`

- **Description:** Name of the express route circuit.
- **Type:** String
- **Default:** ""

### `tags`

- **Type:** Map of strings
- **Default:** {}

## Terraform Provider References

### Resources

- [azurerm_express_route_circuit](https://registry.terraform.io/providers/hashicorp/azurerm/latest/docs/resources/express_route_circuit)
- [azurerm_virtual_network_gateway](https://registry.terraform.io/providers/hashicorp/azurerm/latest/docs/resources/virtual_network_gateway)
- [azurerm_virtual_network_gateway_connection](https://registry.terraform.io/providers/hashicorp/azurerm/latest/docs/resources/virtual_network_gateway_connection)
