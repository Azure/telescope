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

variable "name" {
  description = "Name of the Vnet"
  type        = string
  default     = "client"
}

variable "vm_sku" {
  description = "Value of the VM SKU"
  type        = string
  default     = "Standard_D2ds_v5"
}

variable "nic" {
  description = "Value of the NIC Id"
  type        = string
  default     = ""
}

variable "public_key" {
  description = "public key"
  type        = string
  default     = ""
}

variable "user_data_path" {
  description = "value of the user data path"
  type        = string
  default     = ""
}

variable "vm_config" {
  description = "Configuration for virtual machine"
  type = object({
    name_prefix    = string
    vm_name        = string
    nic_name       = string
    admin_username = string
    zone           = optional(number)
    source_image_reference = object({
      publisher = string
      offer     = string
      sku       = string
      version   = string
    })
    create_vm_extension = bool
  })
}

variable "tags" {
  type    = map(string)
  default = {}
}

variable "ultra_ssd_enabled" {
  description = "Value of the ultra_ssd_enabled"
  type        = bool
  default     = false
}