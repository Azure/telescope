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
  description = "Name of the VMSS"
  type        = string
  default     = "client-vmss"
}

variable "vm_sku" {
  description = "Value of the VM SKU"
  type        = string
  default     = "Standard_D2ds_v5"
}

variable "public_key" {
  description = "public key"
  type        = string
  default     = ""
}

variable "subnet_id" {
  description = "Subnet ID"
  type        = string
  default     = ""
}

variable "ip_configuration_name" {
  description = "IP configuration name"
  type        = string
  default     = ""
}

variable "lb_pool_id" {
  description = "LB Pool ID"
  type        = string
  default     = ""
}

variable "tags" {
  type    = map(string)
  default = {}
}

variable "user_data_path" {
  description = "value of the user data path"
  type        = string
  default     = ""
}

variable "vmss_config" {
  description = "Configuration for virtual machine scale set"
  type = object({
    name_prefix            = string
    vmss_name              = string
    admin_username         = string
    nic_name               = string
    subnet_name            = string
    loadbalancer_pool_name = string
    ip_configuration_name  = string
    number_of_instances    = number
    source_image_reference = object({
      publisher = string
      offer     = string
      sku       = string
      version   = string
    })
  })
}
