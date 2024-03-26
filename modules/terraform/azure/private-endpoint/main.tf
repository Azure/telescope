# create private endpoint for storage account connection

resource "azurerm_private_endpoint" "private_endpoint" {
  name                = var.pe_name
  location            = var.location
  resource_group_name = var.resource_group_name
  tags = var.tags

  subnet_id = var.pe_subnet_id

  private_service_connection {
    name                           = var.pe_name
    private_connection_resource_id = var.resource_id
    is_manual_connection           = var.is_manual_connection
    subresource_names              = var.subresource_names
  }
}