variable "resource_group_name" {
  description = "Name of the resource group"
  type        = string
}

variable "location" {
  description = "Azure region location"
  type        = string
}

variable "tags" {
  description = "Tags to apply to resources"
  type        = map(string)
  default     = {}
}

variable "key_vaults" {
  description = "Map of Key Vault configurations with keys (passed from parent module)"
  type        = map(any)
  default     = {}
}

variable "disk_encryption_set_config" {
  description = "Configuration for Disk Encryption Set with Customer-Managed Keys"
  type = object({
    name            = string                                              # Name of the Disk Encryption Set
    key_vault_name  = string                                              # Name of the Key Vault containing the encryption key
    key_name        = string                                              # Name of the encryption key in the Key Vault
    encryption_type = optional(string, "EncryptionAtRestWithCustomerKey") # Type of encryption
    # Supported values:
    # - EncryptionAtRestWithCustomerKey (default): Disk is encrypted with customer-managed key
    # - EncryptionAtRestWithPlatformAndCustomerKeys: Double encryption (platform + customer key)
    # - ConfidentialVmEncryptedWithCustomerKey: For confidential VMs
    auto_key_rotation_enabled = optional(bool, false) # Enable automatic key rotation
  })
  default = null

  validation {
    condition = (
      var.disk_encryption_set_config == null ? true : (
        length(var.disk_encryption_set_config.name) >= 1 &&
        length(var.disk_encryption_set_config.name) <= 80 &&
        length(var.disk_encryption_set_config.key_vault_name) >= 1 &&
        length(var.disk_encryption_set_config.key_name) >= 1
      )
    )
    error_message = "Disk Encryption Set name must be 1-80 characters, and key_vault_name and key_name must be specified."
  }

  validation {
    condition = (
      var.disk_encryption_set_config == null ? true : contains(
        ["EncryptionAtRestWithCustomerKey", "EncryptionAtRestWithPlatformAndCustomerKeys", "ConfidentialVmEncryptedWithCustomerKey"],
        var.disk_encryption_set_config.encryption_type
      )
    )
    error_message = "encryption_type must be one of: EncryptionAtRestWithCustomerKey, EncryptionAtRestWithPlatformAndCustomerKeys, or ConfidentialVmEncryptedWithCustomerKey."
  }
}
