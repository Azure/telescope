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
    condition = can(
      regex(
        "^(ssh-rsa|ssh-ed25519|ssh-dss|ecdsa-sha2-nistp256|ecdsa-sha2-nistp384|ecdsa-sha2-nistp521) [A-Za-z0-9+/=]+( .*)?$",
        trimspace(var.ssh_public_key)
      )
    )
    error_message = "ssh_public_key must be non-empty and in a valid SSH public key format (e.g., ssh-ed25519, ssh-rsa)."
  }
}

variable "jumpbox_config" {
  description = "Jumpbox configuration"
  type = object({
    role           = string
    name           = string
    vm_size        = optional(string, "Standard_D4s_v3")
    subnet_name = string
    public_ip_name = string
    aks_name       = string
  })
}

variable "public_ips_map" {
  description = "Map of public IP names to their objects containing id and ip_address"
  type = map(object({
    id         = string
    ip_address = string
  }))
}

variable "subnets_map" {
  description = "Map of subnet names to subnet objects"
  type        = map(any)
  default     = {}
}