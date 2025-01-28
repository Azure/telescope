locals {
  nsr_rules_map                = { for rule in var.network_config.nsr_rules : rule.name => rule }
  nat_gateway_associations_map = var.network_config.nat_gateway_associations == null ? {} : { for nat in var.network_config.nat_gateway_associations : nat.nat_gateway_name => nat }
  vnet_name                    = var.network_config.vnet_name
  input_subnet_map             = { for subnet in var.network_config.subnet : subnet.name => subnet }
  subnets_map                  = { for subnet in azurerm_subnet.subnets : subnet.name => subnet }
  network_security_group_name  = var.network_config.network_security_group_name
  expanded_nic_association_map = flatten([
    for nic in var.network_config.nic_public_ip_associations : [
      for i in range(var.nic_count_override > 0 ? var.nic_count_override : nic.count) : {
        nic_name              = (var.nic_count_override > 0 ? var.nic_count_override : nic.count) > 1 ? "${nic.nic_name}-${i + 1}" : nic.nic_name
        subnet_name           = nic.subnet_name
        ip_configuration_name = nic.ip_configuration_name
        public_ip_name        = (var.nic_count_override > 0 ? var.nic_count_override : nic.count) > 1 ? "${nic.public_ip_name}-${i + 1}" : nic.public_ip_name
      }
    ]
  ])
  nic_association_map = { for nic in local.expanded_nic_association_map : nic.nic_name => nic }
  tags                = merge(var.tags, { "role" = var.network_config.role })
}

resource "azurerm_virtual_network" "vnet" {
  name                = local.vnet_name
  address_space       = [var.network_config.vnet_address_space]
  location            = var.location
  resource_group_name = var.resource_group_name
  tags                = local.tags
}

resource "azurerm_subnet" "subnets" {
  for_each = local.input_subnet_map

  name                                          = each.value.name
  resource_group_name                           = var.resource_group_name
  virtual_network_name                          = azurerm_virtual_network.vnet.name
  address_prefixes                              = [each.value.address_prefix]
  service_endpoints                             = each.value.service_endpoints != null ? each.value.service_endpoints : []
  private_link_service_network_policies_enabled = each.value.pls_network_policies_enabled != null ? each.value.pls_network_policies_enabled : true
  dynamic "delegation" {
    for_each = each.value.delegations != null ? each.value.delegations : []
    content {
      name = delegation.value.name
      service_delegation {
        name    = delegation.value.service_delegation_name
        actions = delegation.value.service_delegation_actions
      }
    }
  }
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

  name                           = each.key
  location                       = var.location
  resource_group_name            = var.resource_group_name
  accelerated_networking_enabled = var.accelerated_networking
  tags                           = local.tags

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

module "nat_gateway" {
  source   = "./nat-gateway"
  for_each = local.nat_gateway_associations_map

  nat_gateway_name        = each.value.nat_gateway_name
  location                = var.location
  public_ips              = var.public_ips
  resource_group_name     = var.resource_group_name
  nat_gateway_association = each.value
  subnets_map             = local.subnets_map
  tags                    = local.tags
}
