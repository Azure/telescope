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

variable "public_ips" {
  description = "Map of public IP names to IDs"
  type = map(string)
}

variable "accelerated_networking" {
  description = "Value of the accelerated networking"
  type        = bool
  default     = true
}

variable "network_config" {
  type = object({
    role                 = string
    vnet_name                   = string
    vnet_address_space          = string
    subnet_names                = list(string)
    subnet_address_prefixes     = list(string)
    network_security_group_name = string
    nic_public_ip_associations = list(object({
      nic_name              = string
      subnet_name           = string
      ip_configuration_name = string
      public_ip_name        = string
    }))
    nsr_rules = list(object({
      name                       = string
      priority                   = number
      direction                  = string
      access                     = string
      protocol                   = string
      source_port_range          = string
      destination_port_range     = string
      source_address_prefix      = string
      destination_address_prefix = string
    }))
  })
}


variable "tags" {
  type = map(string)
  default = {
  }
}
