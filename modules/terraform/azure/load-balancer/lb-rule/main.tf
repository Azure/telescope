
resource "azurerm_lb_rule" "lb-rule" {
  count                          = var.type == "Inbound" ? var.rule_count : 0
  name                           = var.rule_count == 1 ? var.role : "${var.role}-${count.index + 1}"
  protocol                       = var.protocol
  frontend_port                  = var.rule_count == 1 ? var.frontend_port : var.frontend_port + count.index + 1
  backend_port                   = var.rule_count == 1 ? var.backend_port : var.backend_port + count.index + 1
  frontend_ip_configuration_name = "${var.frontend_ip_config_role}-lb-frontend-ip"
  loadbalancer_id                = var.lb_id
  backend_address_pool_ids       = [var.lb_pool_id]
  probe_id                       = var.probe_id
  enable_tcp_reset               = var.enable_tcp_reset
  disable_outbound_snat          = true
  idle_timeout_in_minutes        = var.idle_timeout_in_minutes
}


resource "azurerm_lb_outbound_rule" "lb-outbound-rule" {
  count                   = var.type == "Outbound" ? var.rule_count : 0
  name                    = var.role
  protocol                = var.protocol
  loadbalancer_id         = var.lb_id
  backend_address_pool_id = var.lb_pool_id
  enable_tcp_reset        = var.enable_tcp_reset
  idle_timeout_in_minutes = var.idle_timeout_in_minutes
  frontend_ip_configuration {
    name = "${var.frontend_ip_config_role}-lb-frontend-ip"
  }
}
