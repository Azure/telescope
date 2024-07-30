resource "azurerm_proximity_placement_group" "placement_group" {
  count               = var.proximity_placement ? 1 : 0
  name                = var.name
  resource_group_name = var.resource_group_name
  location            = var.location
  tags                = var.tags
}
