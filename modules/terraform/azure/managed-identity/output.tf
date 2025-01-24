output "id" {
  description = "The ID of the managed identity"
  value       = azurerm_user_assigned_identity.managed_identity.id
}
