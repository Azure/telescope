variable "resource_group_name" {
  description = "Value of the resource group name"
  type        = string
}

variable "location" {
  description = "Value of the location"
  type        = string
}

variable "tags" {
  type = map(string)
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

variable "dns_zones" {
  description = "Map of DNS zones created, where the key is the zone name and the value is the zone ID"
  type        = map(string)
  default     = {}
}

variable "k8s_machine_type" {
  description = "Value to replace AKS nodes vm_size"
  type        = string
  default     = null
}

variable "k8s_os_disk_type" {
  description = "Value to replace AKS nodes os_disk_type"
  type        = string
  default     = null
}

variable "network_policy" {
  description = "Value to replace the AKS network_policy. If network_policy is 'azure' or 'cilium', network_dataplane must match or be null."
  type        = string
  default     = null
}

variable "network_dataplane" {
  description = "Value to replace the AKS network_dataplane"
  type        = string
  default     = null
}

variable "aks_aad_enabled" {
  description = "Indicates whether Azure Active Directory integration is enabled for AKS"
  type        = bool
  default     = false
}

variable "key_vaults" {
  description = "Map of Key Vault configurations with keys"
  type        = map(any)
  default     = {}
}

variable "aks_config" {
  type = object({
    role        = string
    aks_name    = string
    dns_prefix  = string
    subnet_name = optional(string, null)
    network_profile = optional(object({
      network_plugin      = optional(string, null)
      network_plugin_mode = optional(string, null)
      network_policy      = optional(string, null)
      network_dataplane   = optional(string, null)
      outbound_type       = optional(string, null)
      pod_cidr            = optional(string, null)
      service_cidr        = optional(string, null)
      dns_service_ip      = optional(string, null)
    }))
    sku_tier     = string
    support_plan = optional(string, "KubernetesOfficial")
    default_node_pool = object({
      name                         = string
      subnet_name                  = optional(string, null)
      node_count                   = number
      vm_size                      = string
      os_sku                       = optional(string, "Ubuntu")
      os_disk_type                 = optional(string, "Managed")
      os_disk_size_gb              = optional(number, null)
      only_critical_addons_enabled = bool
      temporary_name_for_rotation  = string
      max_pods                     = optional(number, null)
      node_labels                  = optional(map(string), {})
      min_count                    = optional(number, null)
      max_count                    = optional(number, null)
      auto_scaling_enabled         = optional(bool, false)
    })
    extra_node_pool = list(object({
      name                 = string
      subnet_name          = optional(string, null)
      node_count           = number
      vm_size              = string
      os_type              = optional(string, null)
      os_sku               = optional(string, "Ubuntu")
      os_disk_type         = optional(string, "Managed")
      os_disk_size_gb      = optional(number, null)
      max_pods             = optional(number, null)
      ultra_ssd_enabled    = optional(bool, false)
      zones                = optional(list(string), [])
      node_taints          = optional(list(string), [])
      node_labels          = optional(map(string), {})
      min_count            = optional(number, null)
      max_count            = optional(number, null)
      auto_scaling_enabled = optional(bool, false)
      priority             = optional(string, "Regular")
      eviction_policy      = optional(string, null)
      spot_max_price       = optional(number, null)
    }))
    role_assignment_list = optional(list(string), [])
    service_mesh_profile = optional(object({
      mode      = string
      revisions = list(string)
    }))
    oidc_issuer_enabled       = optional(bool, false)
    workload_identity_enabled = optional(bool, false)
    kubernetes_version        = optional(string, null)
    edge_zone                 = optional(string, null)
    auto_scaler_profile = optional(object({
      balance_similar_node_groups      = optional(bool, false)
      expander                         = optional(string, "random")
      max_graceful_termination_sec     = optional(string, "600")
      max_node_provisioning_time       = optional(string, "15m")
      max_unready_nodes                = optional(number, 3)
      max_unready_percentage           = optional(number, 45)
      new_pod_scale_up_delay           = optional(string, "10s")
      scale_down_delay_after_add       = optional(string, "10m")
      scale_down_delay_after_delete    = optional(string, "10s")
      scale_down_delay_after_failure   = optional(string, "3m")
      scale_down_unneeded              = optional(string, "10m")
      scale_down_unready               = optional(string, "20m")
      scale_down_utilization_threshold = optional(string, "0.5")
      scan_interval                    = optional(string, "10s")
      empty_bulk_delete_max            = optional(string, "10")
      skip_nodes_with_local_storage    = optional(bool, true)
      skip_nodes_with_system_pods      = optional(bool, true)
    }))
    web_app_routing = optional(object({
      dns_zone_names = list(string)
    }), null)
    kms_config = optional(object({
      key_name       = string
      key_vault_name = string
      network_access = optional(string, "Public")
    }), null)
  })

  validation {
    condition = alltrue([
      for node_pool in var.aks_config.extra_node_pool :
      node_pool.os_type == "Windows" ? length(node_pool.name) <= 6 : true
    ])

    error_message = "Windows agent pool name can not be longer than 6 characters"
  }
}
