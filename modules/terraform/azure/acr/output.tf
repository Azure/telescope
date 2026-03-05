output "acr_pull_scopes_by_aks_cli_role" {
  description = "Map of aks-cli role to list of ACR resource IDs to grant AcrPull on. Computed from acr_config_list.*_aks_cli_roles."
  value       = local.acr_pull_scopes_by_aks_cli_role
}

output "bootstrap_container_registry_resource_id_by_aks_cli_role" {
  description = "Map of aks-cli role to a single ACR resource ID (first pull scope) used for bootstrap_artifact_source."
  value       = local.bootstrap_container_registry_resource_id_by_aks_cli_role
}
