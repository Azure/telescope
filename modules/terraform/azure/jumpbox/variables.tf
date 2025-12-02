variable "resource_group_name" {
  description = "Resource group to deploy the jumpbox into"
  type        = string
}

variable "location" {
  description = "Azure region"
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

variable "jumpbox_config" {
  description = "Jumpbox configuration"
  type = object({
    role           = string
    name           = string
    vm_size        = optional(string, "Standard_D4s_v3")
    nic_name       = string
    aks_name       = string
  })
}

variable "nics_map" {
  description = "Map of NIC names to their IDs"
  type        = map(string)
}
