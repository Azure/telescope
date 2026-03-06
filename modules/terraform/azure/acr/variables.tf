variable "acr_config_list" {
  description = "Optional list of Azure Container Registries (ACR) to create. Each entry can also enable a Private Endpoint + Private DNS integration (Private Link)."
  type = list(object({
    name                          = optional(string, null)
    sku                           = optional(string, "Premium")
    admin_enabled                 = optional(bool, false)
    public_network_access_enabled = optional(bool, true)

    private_endpoint = optional(object({
      subnet_name           = string
      private_dns_zone_name = optional(string, "privatelink.azurecr.io")
    }), null)

    acrpull_aks_cli_roles     = optional(list(string), [])
    contributor_aks_cli_roles = optional(list(string), [])

    cache_rules = optional(list(object({
      name                       = string
      source_repository          = string
      target_repository          = string
      credential_set_resource_id = optional(string, null)
    })), [])
  }))
  default = []
}

variable "resource_group_name" {
  type        = string
  description = "Resource group name where ACR resources will be created."
}

variable "location" {
  type        = string
  description = "Azure region for ACR resources."
}

variable "tags" {
  type        = map(string)
  description = "Tags to apply to ACR resources."
  default     = {}
}

variable "scenario_name" {
  type        = string
  description = "Scenario name used for default ACR name generation."
}

variable "run_id" {
  type        = string
  description = "Run ID used for default ACR name generation and resource group name conventions."
}

variable "subnet_ids_by_name" {
  type        = map(string)
  description = "Map of subnet name to subnet ID."
}

variable "vnet_ids_by_role" {
  type        = map(string)
  description = "Map of network role to virtual network ID."
}

variable "subnet_to_network_role" {
  type        = map(string)
  description = "Map of subnet name to network role (used for Private DNS VNet linking)."
}

variable "aks_cli_roles" {
  type        = list(string)
  description = "List of aks-cli roles to compute ACR pull scopes for."
  default     = []
}
