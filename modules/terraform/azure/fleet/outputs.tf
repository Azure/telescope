output "fleet_name" {
  description = "Name of the Fleet resource (empty when fleet_enabled=false)."
  value       = var.fleet_enabled ? var.fleet_name : ""
}

output "cmp_name" {
  description = "Name of the ClusterMesh profile (empty when fleet_enabled=false)."
  value       = var.fleet_enabled ? var.cmp_name : ""
}

output "member_names" {
  description = "List of fleet member names created."
  value       = var.fleet_enabled ? [for m in var.members : m.member_name] : []
}
