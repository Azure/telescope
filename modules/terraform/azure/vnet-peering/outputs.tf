output "peering_keys" {
  description = "List of peering keys (src_role->dst_role) that were created."
  value       = keys(azurerm_virtual_network_peering.peering)
}
