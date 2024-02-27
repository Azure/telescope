output "name" {
  value = var.skip_resource_group_creation ? data.azurerm_resource_group.existing_rg[0].name : azurerm_resource_group.rg[0].name
}
