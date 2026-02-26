output "aks_cli" {
  description = "Used for unit tests"
  value       = terraform_data.aks_cli
}

output "aks_cli_command" {
  description = "Used for unit tests"
  value       = local.aks_cli_command
}

output "des_reader_kubelet_principal_id" {
  description = "Used for unit tests"
  value       = try(azurerm_role_assignment.des_reader_kubelet[0].principal_id, null)
}

output "des_reader_cluster_principal_id" {
  description = "Used for unit tests"
  value       = try(azurerm_role_assignment.des_reader_cluster[0].principal_id, null)
}
