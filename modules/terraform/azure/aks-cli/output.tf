output "kubelet_object_id" {
  description = "Object ID of the cluster's kubelet managed identity, when requested"
  value       = local.aks_kubelet_object_id
}

output "aks_cli" {
  description = "Used for unit tests"
  value       = terraform_data.aks_cli
}

output "aks_cli_command" {
  description = "Used for unit tests"
  value       = local.aks_cli_command
}
