locals {
  nsr_rules_map                = { for rule in var.network_config.nsr_rules : rule.name => rule }
  vnet_name                    = var.network_config.vnet_name
  subnet_names                 = var.network_config.subnet_names
  subnets_map                  = { for subnet in azurerm_subnet.subnets : subnet.name => subnet }
  subnet_address_prefixes      = var.network_config.subnet_address_prefixes
  subnet_service_endpoints     = var.network_config.subnet_service_endpoints
  pls_network_policies_enabled = var.network_config.pls_network_policies_enabled
  network_security_group_name  = var.network_config.network_security_group_name
  nic_association_map          = { for nic in var.network_config.nic_public_ip_associations : nic.nic_name => nic }
  tags                         = merge(var.tags, { "role" = var.network_config.role })
}

resource "azurerm_virtual_network" "vnet" {
  name                = local.vnet_name
  address_space       = [var.network_config.vnet_address_space]
  location            = var.location
  resource_group_name = var.resource_group_name
  tags                = local.tags
}

resource "azurerm_subnet" "subnets" {
  count = length(local.subnet_names)

  name                                          = local.subnet_names[count.index]
  resource_group_name                           = var.resource_group_name
  virtual_network_name                          = azurerm_virtual_network.vnet.name
  address_prefixes                              = [local.subnet_address_prefixes[count.index]]
  service_endpoints                             = local.subnet_service_endpoints
  private_link_service_network_policies_enabled = local.pls_network_policies_enabled
}


resource "azurerm_network_security_group" "nsg" {
  count               = local.network_security_group_name != "" ? 1 : 0
  name                = local.network_security_group_name
  location            = var.location
  resource_group_name = var.resource_group_name
  tags                = local.tags
}


resource "azurerm_subnet_network_security_group_association" "subnet-nsg-associations" {
  for_each = local.network_security_group_name != "" ? local.subnets_map : {}

  subnet_id                 = each.value.id
  network_security_group_id = azurerm_network_security_group.nsg[0].id
}

resource "azurerm_network_interface" "nic" {
  for_each = local.nic_association_map

  name                          = each.key
  location                      = var.location
  resource_group_name           = var.resource_group_name
  enable_accelerated_networking = var.accelerated_networking
  tags                          = local.tags

  ip_configuration {
    name                          = each.value.ip_configuration_name
    subnet_id                     = local.subnets_map[each.value.subnet_name].id
    private_ip_address_allocation = "Dynamic"
    public_ip_address_id          = each.value.public_ip_name != null ? var.public_ips[each.value.public_ip_name] : null
  }

}

module "nsr" {
  source   = "./network-security-rule"
  for_each = local.nsr_rules_map

  name                        = each.value.name
  priority                    = each.value.priority
  direction                   = each.value.direction
  access                      = each.value.access
  protocol                    = each.value.protocol
  source_port_range           = each.value.source_port_range
  destination_port_range      = each.value.destination_port_range
  source_address_prefix       = each.value.source_address_prefix
  destination_address_prefix  = each.value.destination_address_prefix
  resource_group_name         = var.resource_group_name
  network_security_group_name = azurerm_network_security_group.nsg[0].name
}
