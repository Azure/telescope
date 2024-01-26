locals {
  lb_rules_map          = { for rule in var.loadbalancer_config.lb_rules : rule.role => rule }
  role                  = var.loadbalancer_config.role
  loadbalance_name      = var.loadbalancer_config.loadbalance_name
  loadbalance_pool_name = var.loadbalancer_config.loadbalance_pool_name
}

resource "azurerm_lb" "lb" {
  name                = local.loadbalance_name
  location            = var.location
  resource_group_name = var.resource_group_name
  sku                 = "Standard"

  frontend_ip_configuration {
    name                          = "${local.role}-lb-frontend-ip"
    public_ip_address_id          = var.is_internal_lb ? null : var.public_ip_id
    private_ip_address_allocation = var.is_internal_lb ? "Dynamic" : null
    subnet_id                     = var.is_internal_lb ? var.subnet_id : null
  }
  tags = merge(
    var.tags,
    {
      "role" = local.role
    },
  )
}

resource "azurerm_lb_backend_address_pool" "lb-pool" {
  name            = local.loadbalance_pool_name
  loadbalancer_id = azurerm_lb.lb.id
}

resource "azurerm_lb_probe" "lb-probe" {
  name            = "${local.role}-lb-probe"
  loadbalancer_id = azurerm_lb.lb.id
  protocol        = var.loadbalancer_config.probe_protocol
  port            = var.loadbalancer_config.probe_port
  request_path    = var.loadbalancer_config.probe_request_path
}

module "lb-rule" {
  source   = "./lb-rule"
  for_each = local.lb_rules_map

  role                    = each.key
  type                    = each.value.type
  protocol                = each.value.protocol
  frontend_port           = each.value.frontend_port
  backend_port            = each.value.backend_port
  lb_id                   = azurerm_lb.lb.id
  lb_pool_id              = azurerm_lb_backend_address_pool.lb-pool.id
  probe_id                = azurerm_lb_probe.lb-probe.id
  rule_count              = each.value.rule_count
  enable_tcp_reset        = each.value.enable_tcp_reset
  frontend_ip_config_role = local.role
}
