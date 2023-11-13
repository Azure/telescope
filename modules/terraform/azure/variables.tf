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

variable "vm_sku" {
  description = "Value of the VM SKU"
  type        = string
  default     = "Standard_D2ds_v5"
}

variable "accelerated_networking" {
  description = "Value of the accelerated networking"
  type        = bool
  default     = true
}

variable "job_id" {
  description = "Value of the job id"
  type        = string
  default     = "123456"
}

variable "scenario_name" {
  description = "Name of the scenario"
  type        = string
  default     = ""
}

variable "deletion_delay" {
  description = "Time duration after which the resources can be deleted (e.g., '1h', '2h', '4h')"
  type        = string
  default     = "2h"
}

variable "user_data_path" {
  description = "value of the user data path"
  type        = string
  default     = ""
}

variable "public_ip_names" {
  description = "A list of public IP names"
  type        = list(string)
  default     = ["ingress-pip", "egress-pip"]
}

variable "network_config_list" {
  description = "Configuration for creating the server network."
  type = list(object({
    name_prefix                 = string
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
  }))
}

variable "loadbalancer_config_list" {
  description = "List of Loadbalancer configurations"
  type = list(object({
    name_prefix           = string
    loadbalance_name      = string
    public_ip_name        = string
    loadbalance_pool_name = string
    probe_protocol        = string
    probe_port            = string
    probe_request_path    = string
    lb_rules = list(object({
      type                    = string
      name_prefix             = string
      frontend_port           = number
      backend_port            = number
      protocol                = string
      rule_count              = number
      enable_tcp_reset        = bool
      idle_timeout_in_minutes = number
    }))
  }))
}

variable "vm_config_list" {
  description = "List of configuration for virtual machines"
  type = list(object({
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
  }))
}

variable "vmss_config_list" {
  description = "List of configuration for virtual machine scale sets"
  type = list(object({
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
  }))
}

variable "nic_backend_pool_association_list" {
  description = "List of configuration for nic backend pool associations"
  type = list(object({
    nic_name              = string
    backend_pool_name     = string
    vm_name               = string
    ip_configuration_name = string
  }))
}

variable "data_disk_config_list" {
  description = "List of configuration for data disks"
  type = list(object({
    disk_name              = string
    zone                   = number
  }))
  default     = []
}

variable "data_disk_association_list" {
  description = "List of configuration for data_disk associations"
  type = list(object({
    data_disk_name         = string
    vm_name                = string
  }))
  default     = []
}

variable "data_disk_storage_account_type" {
  description = "Value of the storage_account_type"
  type        = string
  default     = "" # Standard_LRS, StandardSSD_ZRS, Premium_LRS, PremiumV2_LRS, Premium_ZRS, StandardSSD_LRS or UltraSSD_LRS
}

variable "data_disk_size_gb" {
  description = "Value of the disk_size_gb"
  type        = string
  default     = ""
}


variable "data_disk_iops_read_write" {
  description = "Value of the disk_iops_read_write"
  type        = number
  default     = null
}

variable "data_disk_mbps_read_write" {
  description = "Value of the disk_mbps_read_write"
  type        = number
  default     = null
}

variable "data_disk_iops_read_only" {
  description = "Value of the isk_iops_read_only"
  type        = number
  default     = null
}

variable "data_disk_mbps_read_only" {
  description = "Value of the disk_mbps_read_only"
  type        = number
  default     = null
}

variable "data_disk_tier" {
  description = "Value of the tier"
  type        = string
  default     = null
}

variable "ultra_ssd_enabled" {
  description = "Value of ultra_ssd_enabled, only for ultar ssd sku"
  type        = bool
  default     = false
}
