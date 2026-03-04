variable "resource_group_name" {
  description = "Value of the resource group name"
  type        = string
}

variable "location" {
  description = "Value of the location"
  type        = string
}

variable "public_ips" {
  description = "Map of public IP names to their objects containing id and ip_address"
  type = map(object({
    id         = string
    ip_address = string
  }))
}

variable "accelerated_networking" {
  description = "Value of the accelerated networking"
  type        = bool
  default     = true
}

variable "network_config" {
  type = object({
    role               = string
    vnet_name          = string
    vnet_address_space = string
    subnet = list(object({
      name                         = string
      address_prefix               = string
      service_endpoints            = optional(list(string))
      pls_network_policies_enabled = optional(bool)
      delegations = optional(list(object({
        name                       = string
        service_delegation_name    = string
        service_delegation_actions = list(string)
      })))
    }))
    network_security_group_name = string
    nic_public_ip_associations = list(object({
      nic_name              = string
      subnet_name           = string
      ip_configuration_name = string
      # Optional: when omitted or null, the NIC will be created without a public IP.
      public_ip_name = optional(string)
      count          = optional(number, 1)
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
    nat_gateway_associations = optional(list(object({
      nat_gateway_name = string
      public_ip_names  = list(string)
      subnet_names     = list(string)
    })))
  })
}

variable "tags" {
  type = map(string)
}

variable "nic_count_override" {
  description = "value the number of modules to create, overrides tfvars definition if greater than 0"
  type        = number
  default     = 0
}
