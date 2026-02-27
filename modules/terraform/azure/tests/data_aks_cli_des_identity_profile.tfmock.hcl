override_resource {
  target = module.key_vault["kvdes"].azurerm_key_vault.kv[0]
  values = {
    id = "/subscriptions/12345678-1234-1234-1234-123456789012/resourceGroups/123456789/providers/Microsoft.KeyVault/vaults/kvdes-0000"
  }
}

override_resource {
  target = module.key_vault["kvdes"].azurerm_key_vault_key.kms_key["key1"]
  values = {
    id          = "https://kvdes-0000.vault.azure.net/keys/key1/0000000000000000"
    resource_id = "/subscriptions/12345678-1234-1234-1234-123456789012/resourceGroups/123456789/providers/Microsoft.KeyVault/vaults/kvdes-0000/keys/key1"
  }
}

override_resource {
  target = module.disk_encryption_set["des-1"].azurerm_disk_encryption_set.des[0]
  values = {
    id = "/subscriptions/12345678-1234-1234-1234-123456789012/resourceGroups/123456789/providers/Microsoft.Compute/diskEncryptionSets/des-1"
    identity = {
      principal_id = "00000000-0000-0000-0000-000000000555"
      tenant_id    = "00000000-0000-0000-0000-000000000000"
      type         = "SystemAssigned"
    }
  }
}
