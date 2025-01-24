variable "resource_group_name" {
  description = "Value of the resource group name"
  type        = string
  default     = "rg"
}

variable "location" {
  description = "Value of the location"
  type        = string
  default     = "East US"
}

variable "tags" {
  type    = map(string)
  default = null
}

variable "identity_name" {
  type        = string
  description = "value of the user assigned identity name"
  default     = null
}
