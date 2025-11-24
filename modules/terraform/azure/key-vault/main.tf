data "azurerm_client_config" "current" {}

resource "azurerm_key_vault" "kv" {
  count                      = var.key_vault_config != null ? 1 : 0
  name                       = var.key_vault_config.name
  location                   = var.location
  resource_group_name        = var.resource_group_name
  tenant_id                  = data.azurerm_client_config.current.tenant_id
  sku_name                   = "standard"
  rbac_authorization_enabled = true # Enable RBAC mode for role-based access control

  tags = var.tags
}

resource "azurerm_key_vault_key" "kms_key" {
  for_each = var.key_vault_config != null ? {
    for key in var.key_vault_config.keys : key.key_name => key
  } : {}

  name         = each.value.key_name
  key_vault_id = azurerm_key_vault.kv[0].id
  key_type     = "RSA"
  key_size     = 2048
  key_opts     = ["encrypt", "decrypt", "wrapKey", "unwrapKey"]

  depends_on = [
    azurerm_role_assignment.current_user_crypto_officer
  ]
}

# Grant current user/service principal Key Vault Crypto Officer role to create keys
resource "azurerm_role_assignment" "current_user_crypto_officer" {
  count                = var.key_vault_config != null ? 1 : 0
  scope                = azurerm_key_vault.kv[0].id
  role_definition_name = "Key Vault Crypto Officer"
  principal_id         = data.azurerm_client_config.current.object_id
}

# Grant Key Vault Contributor role for purge operations
resource "azurerm_role_assignment" "kv_contributor" {
  count                = var.key_vault_config != null ? 1 : 0
  scope                = azurerm_key_vault.kv[0].id
  role_definition_name = "Key Vault Contributor"
  principal_id         = data.azurerm_client_config.current.object_id
}
