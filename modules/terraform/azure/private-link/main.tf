# create private link service for load balancer
resource "azurerm_private_link_service" "pls" {
  name                = var.pls_name
  location            = var.location
  resource_group_name = var.resource_group_name

  load_balancer_frontend_ip_configuration_ids = [var.pls_lb_fipc_id]

  nat_ip_configuration {
    name                       = "ipconf"
    private_ip_address_version = "IPv4"
    subnet_id                  = var.pls_subnet_id
    primary                    = true
  }

  tags = var.tags
}

resource "azurerm_private_endpoint" "pe" {
  name                = var.pe_name
  location            = var.location
  resource_group_name = var.resource_group_name

  subnet_id = var.pe_subnet_id

  private_service_connection {
    name                           = var.pe_name
    private_connection_resource_id = azurerm_private_link_service.pls.id
    is_manual_connection           = false
  }

  tags = var.tags
}
