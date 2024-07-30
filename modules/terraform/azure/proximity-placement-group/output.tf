output "proximity_placement_group_id" {
  description = "proximity placement group id"
  value       = azurerm_proximity_placement_group.placement_group[0].id
}