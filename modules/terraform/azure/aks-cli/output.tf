output "aks_cli" {
  description = "Used for unit tests"
  value       = terraform_data.aks_cli
}

output "aks_cli_command" {
  description = "Used for unit tests"
  value       = local.aks_cli_command
}

output "des_kubelet_object_id" {
  description = "Used for unit tests"
  value       = local.aks_kubelet_object_id
}

output "des_cluster_principal_id" {
  description = "Used for unit tests"
  value       = local.aks_system_assigned_principal_id
}
