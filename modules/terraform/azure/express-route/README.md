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

### `type` 

- **Description** THe Type of the Virtual Network Gateway. In this case it's ExpressRoute
- **Type** String
- **Default** "ExpressRoute"

### `VPNType` 

- **Description** THe Type of the VPN Used. Default is PolicyBased
- **Type** String
- **Default** "PolicyBased"

### `IPConfiguration` 

- **Description** The IP Linked to the Gateway  contains values of name, public_ip_address_id = the public IP created for the gateway ,private_ip_address_allocation = "Dynamic" and subnet_id = the subnet created for the gateway 
- **Type** Object


## Virtual Network Gateway Connection - Connects the Virtual Network Gateway to the Express Route 

### `resource_group_name`

- **Description:** Name of the resource group where the virtual network gateway will be created.
- **Type:** String
- **Default:** "rg"

### `location`

- **Description:** Azure region where the virtual network gateway  will be deployed.
- **Type:** String
- **Default:** "eastus"

### `name`

- **Description:** Name of the virtual network gateway 
- **Type:** String
- **Default:** ""

### `type`

- **Description:** Type of the virtual network gateway. Default is ExpressRoute
- **Type:** String
- **Default:** "ExpressRoute"

### `virtual_network_gateway_id`

- **Description:** ID of the virtual network gateway. Was created above 
- **Type:** String

### `tags`

- **Type:** Map of strings
- **Default:** {}

## Terraform Provider References

### Resources

- [azurerm_virtual_network_gateway](https://registry.terraform.io/providers/hashicorp/azurerm/latest/docs/resources/virtual_network_gateway)
- [azurerm_virtual_network_gateway_connection](https://registry.terraform.io/providers/hashicorp/azurerm/latest/docs/resources/virtual_network_gateway_connection)
