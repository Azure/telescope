output "cluster_name" {
  description = "Name of the QAD-enabled AKS cluster"
  value       = var.qad_config.aks_name
}

output "minimum_aks_preview_version" {
  description = "Minimum supported aks-preview extension version"
  value       = local.minimum_aks_preview_version
}

output "create_command" {
  description = "Azure CLI command used to create the QAD-enabled AKS cluster"
  value       = local.create_command
}

output "create_arguments" {
  description = "Deterministic Azure CLI arguments used to create the QAD-enabled AKS cluster"
  value       = local.create_arguments
}

output "node_pool_commands" {
  description = "Azure CLI commands used to create QAD-enabled user node pools"
  value       = local.node_pool_commands
}
