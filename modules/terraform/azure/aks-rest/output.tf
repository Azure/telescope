output "aks_rest" {
  description = "Used for unit tests"
  value       = terraform_data.aks_rest
}

output "az_rest_put_command" {
  description = "Used for unit tests - the generated az rest PUT command"
  value       = local.az_rest_put_command
}

output "az_rest_delete_command" {
  description = "Used for unit tests - the generated az aks delete command"
  value       = local.az_rest_delete_command
}

output "request_body" {
  description = "Used for debugging - the JSON request body"
  value       = local.request_body
  sensitive   = false
}
