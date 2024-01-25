output "lb_pool_id" {
  value = azurerm_lb_backend_address_pool.lb-pool.id
}

output "lb_fipc_id" {
  value = azurerm_lb.lb.frontend_ip_configuration.0.id
}