output "acr_pull_enabled_by_aks_cli_role" {
  description = "Map of aks-cli role to a plan-known boolean indicating whether to enable kubelet identity + ACR pull grants for that role."
  value       = local.acr_pull_enabled_by_aks_cli_role
}

output "acr_pull_scopes_map_by_aks_cli_role" {
  description = "Map of aks-cli role to map of stable keys -> ACR scope IDs to grant AcrPull on. Use this to drive plan-stable for_each downstream."
  value       = local.acr_pull_scopes_map_by_aks_cli_role
}

output "bootstrap_container_registry_resource_id_by_aks_cli_role" {
  description = "Map of aks-cli role to a single ACR resource ID (first pull scope) used for bootstrap_artifact_source."
  value       = local.bootstrap_container_registry_resource_id_by_aks_cli_role
}
