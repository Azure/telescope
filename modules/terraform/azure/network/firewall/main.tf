resource "azurerm_firewall" "firewall" {
  name                = var.firewall_config.name
  location            = var.location
  resource_group_name = var.resource_group_name
  sku_name            = var.firewall_config.sku_name
  sku_tier            = var.firewall_config.sku_tier
  firewall_policy_id  = var.firewall_config.firewall_policy_id
  tags                = var.tags

  ip_configuration {
    name                 = var.firewall_config.ip_configuration_name
    subnet_id            = var.subnets_map[var.firewall_config.subnet_name].id
    public_ip_address_id = var.public_ips[var.firewall_config.public_ip_name]
  }
}
