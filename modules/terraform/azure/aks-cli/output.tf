output "aks_cli" {
  description = "Used for unit tests"
  value       = terraform_data.aks_cli
}

output "aks_cli_command" {
  description = "Used for unit tests"
  value       = local.aks_cli_command
}
output "aks_cli_identity_arguments" {
  description = "Identity arguments used by az aks create, independent of apply-time tags."
  value       = [local.managed_identity_parameter, local.kubelet_identity_parameter]
}
