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
    pe_name = optional(string, "private-endpoint")
    pe_subnet_name = string
    psc_name = optional(string, "private-service-connection")
    private_connection_resource_id = optional(string, "")
    subresource_names = optional(list(string, ["blob"]))
  })
  default = null
}

variable "tags" {
  type = map(string)
  default = {
  }
}