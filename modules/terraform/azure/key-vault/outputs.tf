output "key_vault_id" {
  description = "Key Vault ID (used for RBAC role assignments)"
  value       = try(azurerm_key_vault.kv[0].id, null)
}

output "key_ids" {
  description = "Map of Key names to Key IDs: {key_name => key_id}"
  value = {
    for k, v in azurerm_key_vault_key.kms_key :
    v.name => v.id
  }
}
