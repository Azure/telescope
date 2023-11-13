resource "azurerm_public_ip" "pip" {
  count = length(var.public_ip_names)

  name                = var.public_ip_names[count.index]
  location            = var.location
  resource_group_name = var.resource_group_name
  allocation_method   = "Static"
  sku                 = "Standard"
  tags                = var.tags
}
