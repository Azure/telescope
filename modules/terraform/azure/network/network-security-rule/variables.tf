variable "name" {
  description = "Name for the network security rule."
  type        = string
}

variable "priority" {
  description = "Priority for the network security rule."
  type        = number
  validation {
    condition     = var.priority >= 120 && var.priority <= 4096
    error_message = "Priority must be between 120 and 4096."
  }
}

variable "direction" {
  description = "Direction for the network security rule."
  type        = string
}

variable "access" {
  description = "Access for the network security rule."
  type        = string
}

variable "protocol" {
  description = "Protocol for the network security rule."
  type        = string
}

variable "source_port_range" {
  description = "Source port range for the network security rule."
  type        = string
}

variable "destination_port_range" {
  description = "Destination port range for the network security rule."
  type        = string
}

variable "source_address_prefix" {
  description = "Source address prefix for the network security rule."
  type        = string
}

variable "destination_address_prefix" {
  description = "Destination address prefix for the network security rule."
  type        = string
}

variable "resource_group_name" {
  description = "Resource group name for the network security rule."
  type        = string
}

variable "network_security_group_name" {
  description = "Network security group name for the network security rule."
  type        = string
}
