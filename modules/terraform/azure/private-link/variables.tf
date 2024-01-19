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


variable "pls_name" {
  description = "Value of the private link service"
  type        = string
  default     = "pls"
}


variable "pls_subnet_id" {
  description = "ID of the subnet"
  type        = string
  default     = ""
}

variable "pls_lb_fipc_id" {
  description = "ID of the load balancer frontend ip configuration"
  type        = string
  default     = ""
}


variable "pe_name" {
  description = "Value of the private endpoint name"
  type        = string
  default     = "pe"
}


variable "pe_subnet_id" {
  description = "ID of the subnet"
  type        = string
  default     = ""
}

variable "tags" {
  type = map(string)
  default = {
  }
}