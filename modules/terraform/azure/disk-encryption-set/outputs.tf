output "disk_encryption_set_id" {
  description = "The ID of the Disk Encryption Set (for use with --node-osdisk-diskencryptionset-id in AKS CLI)"
  value       = var.disk_encryption_set_config != null ? azurerm_disk_encryption_set.des[0].id : null
}
