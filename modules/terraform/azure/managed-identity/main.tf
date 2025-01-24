resource "azurerm_user_assigned_identity" "userassignedidentity" {
  location            = var.location
  name                = var.user_assigned_identity_name
  resource_group_name = var.resource_group_name
  tags                = var.tags
}
