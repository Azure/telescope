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

variable "tags" {
  type = map(string)
  default = {
  }
}
