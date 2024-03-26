variable "pe_name" {
  description = "Value of the private endpoint name"
  type        = string
  default     = "pe"
}


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

variable "is_manual_connection" {
  description = "boolean value for private endpoint manual connection"
  type = bool
  default = false
}

variable "subresource_names" {
  description = "string type list of subresource names connected to private endpoint"
  type = list(string)
  default = ["blob"]
}

variable "tags" {
  type = map(string)
  default = {
  }
}