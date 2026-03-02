output "aks_cli" {
  description = "Used for unit tests"
  value       = terraform_data.aks_cli
}

output "aks_cli_command" {
  description = "Used for unit tests"
  value       = local.aks_cli_command
}

output "aks_rest_put_command" {
  description = "Used for unit tests"
  value       = local.aks_rest_put_command
}