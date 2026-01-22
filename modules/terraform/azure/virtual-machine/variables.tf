variable "resource_group_name" {
  description = "Resource group to deploy the virtual machine into"
  type        = string
}

variable "location" {
  description = "Azure region"
  type        = string
}

variable "tags" {
  description = "Tags applied to all virtual machine resources"
  type        = map(string)
  default     = {}
}

variable "ssh_public_key" {
  description = "SSH public key authorized on the virtual machine"
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

variable "vm_config" {
  description = "Virtual machine configuration"
  type = object({
    # Basic VM configuration
    role           = string
    name           = string
    vm_size        = optional(string, "Standard_D4s_v3")
    admin_username = optional(string, "azureuser")

    # Network configuration - use NIC name from nics_map
    nic_name = string

    # AKS integration (optional)
    aks_name = optional(string, null)

    # OS disk configuration
    os_disk = optional(object({
      caching              = optional(string, "ReadWrite")
      storage_account_type = optional(string, "Standard_LRS")
      disk_size_gb         = optional(number, 64)
    }), {})

    # Image configuration
    image = optional(object({
      publisher = optional(string, "Canonical")
      offer     = optional(string, "ubuntu-24_04-lts")
      sku       = optional(string, "server")
      version   = optional(string, "latest")
    }), {})

    # NSG configuration
    nsg = optional(object({
      enabled = optional(bool, false)
      rules = optional(list(object({
        name                   = string
        priority               = number
        direction              = optional(string, "Inbound")
        access                 = optional(string, "Allow")
        protocol               = optional(string, "Tcp")
        source_port_range      = optional(string, "*")
        destination_port_range = string
        # WARNING: The default "*" for source_address_prefix allows traffic from any source on the internet.
        # In production, you should provide a more restrictive CIDR or IP range instead of relying on this default.
        source_address_prefix = optional(string, "*")
        # NOTE: The default "*" for destination_address_prefix allows traffic to any destination.
        # Consider narrowing this in production environments where possible.
        destination_address_prefix = optional(string, "*")
      })), [])
    }), {})

    # Cloud-init template file name in templates/ folder
    cloud_init_template = optional(string, "cloud-init.tpl")

    # VM-specific tags (merged with global tags)
    vm_tags = optional(map(string), {})
  })
}

variable "nics_map" {
  description = "Map of NIC names to NIC IDs"
  type        = map(string)
  default     = {}
}
