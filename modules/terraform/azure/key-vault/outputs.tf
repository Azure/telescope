output "key_vaults" {
  description = "Key Vault with all its keys and their IDs"
  value = {
    id = try(azurerm_key_vault.kv[0].id, null)
    keys = {
      for key_path, key in azurerm_key_vault_key.kms_key :
      key.name => {
        id          = key.id
        resource_id = key.resource_id
      }
    }
  }
}
