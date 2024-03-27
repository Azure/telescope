variable "location" {
  description = "Location of private endpoint"
  type        = string
  default     = "East US"
}


variable "resource_group_name" {
  description = "Value of the resource group name"
  type        = string
  default     = "rg"
}


variable "pe_subnet_id" {
  description = "ID of the private endpoint's subnet"
  type        = string
  default     = ""
}

variable "resource_id" {
  description = "private service connection resource id"
  type        = string
  default     = ""
}

variable "pe_config" {
  description = "configuration for a private endpoint"
  type = object({
    pe_name = string
    pe_subnet_name = string
    is_manual_connection = bool
    subresource_names = list(string)
  })
  default = null
}

variable "tags" {
  type = map(string)
  default = {
  }
}