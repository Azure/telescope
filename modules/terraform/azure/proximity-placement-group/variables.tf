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

variable "name" {
  description = "Name of the placement group"
  type = "string"
  default = ""
}

variable "tags" {
  type = map(string)
  default = {
  }
}
