variable "resource_group_name" {
  description = "Value of the resource group name"
  type        = string
}

variable "location" {
  description = "Value of the location"
  type        = string
}

variable "tags" {
  description = "value of the tags"
  type        = map(string)
}

variable "subnet_id" {
  description = "Subnet ID"
  type        = string
  default     = null
}

variable "vnet_id" {
  description = "Vnet id"
  type        = string
  default     = null
}

variable "subnets" {
  description = "Maps of subnets"
  type        = map(string)
  default     = {}
}

variable "aks_config" {
  type = object({
    role        = string
    aks_name    = string
    dns_prefix  = string
    subnet_name = optional(string, null)
    network_profile = optional(object({
      network_plugin      = optional(string, "azure")
      network_plugin_mode = optional(string, "overlay")
      network_policy      = optional(string, null)
      ebpf_data_plane     = optional(string, null)
      outbound_type       = optional(string, null)
      pod_cidr            = optional(string, null)
    }))
    sku_tier = string
    default_node_pool = object({
      name                         = string
      subnet_name                  = optional(string, null)
      node_count                   = number
      vm_size                      = string
      os_sku                       = optional(string, "Ubuntu")
      os_disk_type                 = optional(string, "Managed")
      only_critical_addons_enabled = bool
      temporary_name_for_rotation  = optional(string, "defaulttmp")
      max_pods                     = optional(number, 110)
      min_count                    = optional(number, 2)
      max_count                    = optional(number, 5)
      enable_auto_scaling          = optional(bool, true)
    })
    extra_node_pool = list(object({
      name                = string
      subnet_name         = optional(string, null)
      node_count          = number
      vm_size             = string
      os_sku              = optional(string, "Ubuntu")
      os_disk_type        = optional(string, "Managed")
      max_pods            = optional(number, 110)
      min_count           = optional(number, 2)
      max_count           = optional(number, 100)
      ultra_ssd_enabled   = optional(bool, false)
      zones               = optional(list(string), [])
      node_taints         = optional(list(string), [])
      enable_auto_scaling = optional(bool, true)
    }))
    role_assignment_list = optional(list(string), [])
    service_mesh_profile = optional(object({
      mode = string
    }))
    kubernetes_version = optional(string, null)
  })
}
