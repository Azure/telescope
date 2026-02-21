output "aks_cli" {
  description = "Used for unit tests"
  value       = terraform_data.aks_cli
}

output "aks_cli_command" {
  description = "Used for unit tests"
  value       = local.aks_cli_command
}

output "managed_identity_id" {
  description = "Resource ID of the user-assigned managed identity created for the AKS cluster (null if not created)."
  value       = try(azurerm_user_assigned_identity.userassignedidentity[0].id, null)
}

output "managed_identity_principal_id" {
  description = "Principal ID of the user-assigned managed identity created for the AKS cluster (null if not created)."
  value       = try(azurerm_user_assigned_identity.userassignedidentity[0].principal_id, null)
}