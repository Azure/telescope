# Azure Route Table Module

This module creates an Azure Route Table with custom routes and associates it with subnets.

## Input Variables

### `route_table_config`

- **Description:** Configuration for the route table.
- **Type:** Object
  - `name`: Name of the route table
  - `bgp_route_propagation_enabled`: Whether to enable BGP route propagation (optional, default: true)
  - `routes`: List of routes to create
    - `name`: Name of the route
    - `address_prefix`: Destination address prefix (e.g., "0.0.0.0/0")
    - `next_hop_type`: Type of next hop (e.g., "VirtualAppliance", "VnetLocal", "Internet", "None")
    - `next_hop_in_ip_address`: IP address of next hop (required when next_hop_type is "VirtualAppliance")
  - `subnet_associations`: List of subnets to associate with the route table
    - `subnet_name`: Name of the subnet to associate

### `resource_group_name`

- **Description:** Name of the resource group where the route table will be created.
- **Type:** String

### `location`

- **Description:** Azure region where the route table will be deployed.
- **Type:** String

### `subnets_map`

- **Description:** Map of subnet names to subnet objects (typically from network module output).
- **Type:** Map of objects with `id` attribute

### `tags`

- **Description:** Tags to apply to the route table.
- **Type:** Map of strings
- **Default:** {}

## Usage Example

```hcl
module "route_table" {
  source = "./route-table"

  route_table_config = {
    name                         = "aks-udr-route-table"
    bgp_route_propagation_enabled = true
    routes = [
      {
        name                   = "internet-route"
        address_prefix         = "0.0.0.0/0"
        next_hop_type          = "VirtualAppliance"
        next_hop_in_ip_address = "10.0.1.4"
      }
    ]
    subnet_associations = [
      {
        subnet_name = "aks-subnet"
      }
    ]
  }

  resource_group_name = "my-rg"
  location            = "East US"
  subnets_map         = module.network.subnets_map
  tags = {
    environment = "production"
  }
}
```
