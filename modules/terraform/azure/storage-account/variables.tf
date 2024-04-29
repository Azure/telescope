variable "resource_group_name" {
  description = "Value of the resource group name"
  type        = string
  default     = "cle-rg"
}

variable "location" {
  description = "Value of the location"
  type        = string
  default     = "East US"
}

variable "storage_account_name" {
  description = "storage accont name"
  type        = string
  default     = ""
}

variable "storage_account_tier" {
  description = "storage accont tier"
  type        = string
  default     = ""
}

variable "storage_account_kind" {
  description = "storage accont kind"
  type        = string
  default     = ""
}

variable "storage_account_replication_type" {
  description = "storage accont replication type"
  type        = string
  default     = ""
}

variable "storage_share_config" {
  description = "storage share config"
  type = object({
    name             = string
    quota            = number
    access_tier      = string
    enabled_protocol = string
  })
  default = null
}

variable "storage_blob_config" {
  description = "storage container blob config"
  type = object({
    container_name = string
    container_access = string
    blob_name = string
    source_file_path = string
  })
  default = null
}

variable "storage_network_rules_config" {
  description = "storage network rules config"
  type = object({
    default_action             = string
    virtual_network_subnet_ids = list(string)
  })
  default = null
}

variable "enable_https_traffic_only" {
  description = "enable https traffic only"
  type        = bool
  default     = true
}

variable "tags" {
  type = map(string)
  default = {
  }
}
