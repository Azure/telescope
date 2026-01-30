data "azurerm_client_config" "current" {}

# Disk Encryption Set for Azure managed disks with Customer-Managed Keys
# Reference: https://learn.microsoft.com/en-us/azure/aks/azure-disk-customer-managed-keys
resource "azurerm_disk_encryption_set" "des" {
  count = var.disk_encryption_set_config != null ? 1 : 0

  name                      = var.disk_encryption_set_config.name
  location                  = var.location
  resource_group_name       = var.resource_group_name
  key_vault_key_id          = local.key_vault_key_id
  encryption_type           = var.disk_encryption_set_config.encryption_type
  auto_key_rotation_enabled = var.disk_encryption_set_config.auto_key_rotation_enabled

  identity {
    type = "SystemAssigned"
  }

  tags = var.tags
}

locals {
  # Get the Key Vault key ID from the key_vaults map
  key_vault_key_id = var.disk_encryption_set_config != null ? (
    try(
      var.key_vaults[var.disk_encryption_set_config.key_vault_name].keys[var.disk_encryption_set_config.key_name].id,
      error("Specified key '${var.disk_encryption_set_config.key_name}' does not exist in Key Vault '${var.disk_encryption_set_config.key_vault_name}'")
    )
  ) : null

  key_vault_id = var.disk_encryption_set_config != null ? (
    try(
      var.key_vaults[var.disk_encryption_set_config.key_vault_name].id,
      error("Specified Key Vault '${var.disk_encryption_set_config.key_vault_name}' does not exist in Key Vaults")
    )
  ) : null

  key_vault_key_resource_id = var.disk_encryption_set_config != null ? (
    try(
      var.key_vaults[var.disk_encryption_set_config.key_vault_name].keys[var.disk_encryption_set_config.key_name].resource_id,
      error("Specified key '${var.disk_encryption_set_config.key_name}' resource_id not found in Key Vault '${var.disk_encryption_set_config.key_vault_name}'")
    )
  ) : null

}

locals {
  # Check if both disk_encryption_set_config and required key vault exist
  should_create_role_assignments = (
    var.disk_encryption_set_config != null &&
    length(var.key_vaults) > 0 &&
    contains(keys(var.key_vaults), var.disk_encryption_set_config.key_vault_name)
  )
}

# Grant DiskEncryptionSet identity access to Key Vault for wrap/unwrap key operations
# Required for the DES to use the customer-managed key for encryption
resource "azurerm_role_assignment" "des_key_vault_crypto_user" {
  count = local.should_create_role_assignments ? 1 : 0

  scope                = local.key_vault_id
  role_definition_name = "Key Vault Crypto Service Encryption User"
  principal_id         = azurerm_disk_encryption_set.des[0].identity[0].principal_id
}

# Role assignment at the key level for wrap/unwrap operations
resource "azurerm_role_assignment" "des_key_crypto_user" {
  count = local.should_create_role_assignments ? 1 : 0

  scope                = local.key_vault_key_resource_id
  role_definition_name = "Key Vault Crypto Service Encryption User"
  principal_id         = azurerm_disk_encryption_set.des[0].identity[0].principal_id
}
