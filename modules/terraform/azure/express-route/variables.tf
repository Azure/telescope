variable "resource_group_name" {
  description = "Value of the resource group name"
  type        = string
  default     = "rg"
}

variable "location" {
  description = "Value of the location"
  type        = string
  default     = "eastus"
}

variable "vnet_gateway_config" {
  description = "Configuration for vnet gateway"
  type = object({
    name     = string
    type     = string
    vpn_type = string
    ip_configuration = object({
      name                          = string
      public_ip_address_id          = string
      private_ip_address_allocation = string
      subnet_id                     = string
    })
    vnet_gateway_connection = object({
      connection_name = string
      type = string 
    })
  })
}

variable "tags" {
  type    = map(string)
  default = {}
}