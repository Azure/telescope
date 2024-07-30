resource "azurerm_proximity_placement_group" "placement_group" {
  name                = var.name
  resource_group_name = var.resource_group_name
  location            = var.location
  tags                = var.tags
}
