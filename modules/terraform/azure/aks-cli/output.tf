output "aks_cli" {
  description = "Used for unit tests"
  value       = terraform_data.aks_cli
}

output "aks_cli_command" {
  description = "Used for unit tests"
  value       = local.aks_cli_command
}

output "role_assignments" {
  description = "Role assignments configuration for unit tests"
  value       = local.role_assignments
}

output "role_assignment_resources" {
  description = "Role assignment terraform_data resources for unit tests"
  value       = terraform_data.role_assignment
}