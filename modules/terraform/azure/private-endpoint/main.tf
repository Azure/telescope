# create private endpoint 

resource "azurerm_private_endpoint" "pe" {
  name                = var.pe_name
  location            = var.location
  resource_group_name = var.resource_group_name

  subnet_id = var.pe_subnet_name

  private_service_connection {
    name                           = var.pe_name
    private_connection_resource_id = var.storage_account_name
    is_manual_connection           = false
    subresource_names              = ["blob"]
  }
}