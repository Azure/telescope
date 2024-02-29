# create private endpoint for storage account connection

resource "azurerm_private_endpoint" "private_endpoint" {
  name                = var.pe_name
  location            = var.location
  resource_group_name = var.resource_group_name

  subnet_id = var.pe_subnet_id
}