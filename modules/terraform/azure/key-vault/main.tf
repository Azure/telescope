data "azurerm_client_config" "current" {}

locals {
  key_vault_role_assignments = var.key_vault_config != null ? toset([
    # Grant current user/service principal Key Vault Crypto Officer role to create keys
    "Key Vault Crypto Officer",
    # Grant Key Vault Contributor role for purge operations
    "Key Vault Contributor"
  ]) : toset([])
}
resource "random_string" "kv_suffix" {
  count   = var.key_vault_config != null ? 1 : 0
  length  = 4
  special = false
  upper   = false
  numeric = true
}
resource "azurerm_key_vault" "kv" {
  count                      = var.key_vault_config != null ? 1 : 0
  name                       = "${lower(var.key_vault_config.name)}-${random_string.kv_suffix[0].result}"
  location                   = var.location
  resource_group_name        = var.resource_group_name
  tenant_id                  = data.azurerm_client_config.current.tenant_id
  sku_name                   = "standard"
  rbac_authorization_enabled = true
  purge_protection_enabled   = true
  soft_delete_retention_days = 7

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
    azurerm_role_assignment.current_user_kv_roles
  ]
}

resource "azurerm_role_assignment" "current_user_kv_roles" {
  for_each             = local.key_vault_role_assignments
  scope                = azurerm_key_vault.kv[0].id
  role_definition_name = each.value
  principal_id         = data.azurerm_client_config.current.object_id
}