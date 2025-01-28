# Azure Virtual Network Module

This module provisions virtual networks in Azure. It allows you to create and configure virtual networks with customizable settings, including subnets, security groups, network interfaces (NICs), and NIC associations.


## Input Variables

### `resource_group_name`

- **Description:** Name of the resource group where the virtual network will be created.
- **Type:** String

### `location`

- **Description:** Azure region where the virtual network will be deployed.
- **Type:** String

### `public_ips`

- **Description:** Map of public IP names to IDs.
- **Type:** Map of string
- **Default:** {}

### `accelerated_networking`

- **Description:** Indicates whether accelerated networking is enabled.
- **Type:** Boolean
- **Default:** true

### `network_config`

- **Description:** Configuration for the virtual network.
- **Type:** Object
  - `role`: Role of the virtual network
  - `vnet_name`: Name of the virtual network
  - `vnet_address_space`: Address space of the virtual network
  - `subnet`: List of subnets within the virtual network
  - `network_security_group_name`: Name of the network security group
  - `nic_public_ip_associations`: List of NIC public IP associations
    - `nic_name`: Name of the NIC
    - `subnet_name`: Name of the subnet
    - `ip_configuration_name`: Name of the ip configuration
    - `public_ip_name`: Name of the pip associated to this NIC
    - `count`: Optional, copies of this nic association to make, with nic_name and public_ip_name acting as prefix
  - `nsr_rules`: List of network security rules
  - `nat_gateway_associations`: Optional list of NAT gateway associations
- **Example:** Refer to your specific configuration

### `tags`

- **Type:** Map of strings

## Usage Example

```hcl
module "virtual_network" {
  source = "./virtual-network"

  resource_group_name = "my-rg"
  location            = "West Europe"
  public_ips = {
    "public-ip-1" = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/my-rg/providers/Microsoft.Network/publicIPAddresses/public-ip-1"
    "public-ip-2" = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/my-rg/providers/Microsoft.Network/publicIPAddresses/public-ip-2"
  }
  accelerated_networking = true
  network_config = {
    role               = "web"
    vnet_name          = "web-vnet"
    vnet_address_space = "10.0.0.0/16"
    subnet = [
      {
        name                         = "web-subnet"
        address_prefix               = "10.0.1.0/24"
        service_endpoints            = ["Microsoft.Storage"]
        pls_network_policies_enabled = true
      }
    ]
    network_security_group_name = "web-nsg"
    nic_public_ip_associations = [
      {
        nic_name              = "web-nic"
        subnet_name           = "web-subnet"
        ip_configuration_name = "web-ip-config"
        public_ip_name        = "web-public-ip"
        count                 = 1 # Optional. Will leave the definition unchanged if its 1, but if greater than 1 
                                  # will create copies with nic_name web-nic-1 web-nic-2 etc 
                                  # and public_ip_name web-public-ip-1 web-public-ip-2 etc
      }
    ]
    nsr_rules = [
      {
        name                       = "web-nsr"
        priority                   = 100
        direction                  = "Inbound"
        access                     = "Allow"
        protocol                   = "TCP"
        source_port_range          = "*"
        destination_port_range     = "80"
        source_address_prefix      = "*"
        destination_address_prefix = "*"
      }
    ]
    nat_gateway_associations = [
      {
        nat_gateway_name = "web-nat-gw"
        public_ip_names   = ["web-nat-gw-public-ip"]
        subnet_names      = ["web-subnet"]
      }
    ]
  }

  tags = {
    environment = "production"
    project     = "example"
  }
}
```

# Virtual Network Module Outputs

This module provides the following outputs:

## `network_security_group_name`

- **Description:** Name of the network security group associated with the virtual network.
- **Type:** String
- **Example:** "my-nsg"

## `nics`

- **Description:** Map of network interface controller (NIC) names to their IDs associated with the virtual network.
- **Type:** Map
- **Example:** `{ "nic1" => "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/my-rg/providers/Microsoft.Network/networkInterfaces/nic1", "nic2" => "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/my-rg/providers/Microsoft.Network/networkInterfaces/nic2" }`

## `subnets`

- **Description:** Map of subnet names to their IDs within the virtual network.
- **Type:** Map
- **Example:** `{ "subnet1" => "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/my-rg/providers/Microsoft.Network/virtualNetworks/my-vnet/subnets/subnet1", "subnet2" => "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/my-rg/providers/Microsoft.Network/virtualNetworks/my-vnet/subnets/subnet2" }`

## `vnet_id`

- **Description:** ID of the virtual network.
- **Type:** String
- **Example:** "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/my-rg/providers/Microsoft.Network/virtualNetworks/my-vnet"

## Terraform Provider References

### Resources

- [azurerm_virtual_network Documentation](https://registry.terraform.io/providers/hashicorp/azurerm/latest/docs/resources/virtual_network)
- [azurerm_subnet Documentation](https://registry.terraform.io/providers/hashicorp/azurerm/latest/docs/resources/subnet)
- [azurerm_network_security_group Documentation](https://registry.terraform.io/providers/hashicorp/azurerm/latest/docs/resources/network_security_group)
- [azurerm_subnet_network_security_group_association Documentation](https://registry.terraform.io/providers/hashicorp/azurerm/latest/docs/resources/subnet_network_security_group_association)
- [azurerm_network_interface Documentation](https://registry.terraform.io/providers/hashicorp/azurerm/latest/docs/resources/network_interface)
