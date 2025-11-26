variable "name" {
  description = "Jumpbox virtual machine name"
  type        = string
}

variable "resource_group_name" {
  description = "Resource group to deploy the jumpbox into"
  type        = string
}

variable "location" {
  description = "Azure region"
  type        = string
}

variable "subnet_id" {
  description = "Subnet where the jumpbox NIC will be placed"
  type        = string
}

variable "tags" {
  description = "Tags applied to jumpbox resources"
  type        = map(string)
  default     = {}
}

variable "ssh_public_key" {
  description = "SSH public key authorized on the jumpbox"
  type        = string
  sensitive   = true

  validation {
    condition     = trimspace(var.ssh_public_key) != ""
    error_message = "ssh_public_key must be a non-empty value"
  }
}

variable "vm_size" {
  description = "Virtual machine size for the jumpbox"
  type        = string
  default     = "Standard_D4s_v3"
}

