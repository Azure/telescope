
data "azurerm_resource_group" "existing_rg" {
  count = var.skip_resource_group_creation ? 1 : 0
  name  = var.resource_group_name
}

resource "azurerm_resource_group" "rg" {
  count    = var.skip_resource_group_creation ? 0 : 1
  name     = var.resource_group_name
  location = var.location
  tags     = var.tags
}
