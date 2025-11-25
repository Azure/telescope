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

variable "key_vault_config" {
  description = "Key Vault configuration for AKS KMS encryption"
  type = object({
    name = string # Key Vault name (3-24 chars, globally unique)
    keys = list(object({
      key_name = string # Encryption key name
    }))
  })
  default = null

  validation {
    condition = (
      var.key_vault_config == null ? true : (
        length(var.key_vault_config.name) >= 3 &&
        length(var.key_vault_config.name) <= 20 &&
        length(var.key_vault_config.keys) >= 1
      )
    )
    error_message = "Key Vault name must be 3-20 characters (total 24 after adding 4-char random suffix), and at least one key must be defined."
  }
}
