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

variable "skip_resource_group_creation" {
  description = "Flag to skip the resource group creation"
  type        = bool
  default     = false
}

variable "tags" {
  type = map(string)
  default = {
  }
}
