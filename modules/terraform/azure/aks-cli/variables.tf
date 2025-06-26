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

variable "tags" {
  type = map(string)
  default = {
  }
}

variable "subnet_id" {
  description = "Value of the subnet id"
  type        = string
  default     = null
}

variable "subnets" {
  description = "Maps of subnets"
  type        = map(string)
  default     = {}
}

variable "node_subnet_id" {
  description = "Value of the subnet ID used for Node IPs"
  type        = string
  default     = null
}

variable "pod_subnet_id" {
  description = "Value of the subnet ID used for Pod IPs"
  type        = string
  default     = null
}

variable "pod_ip_allocation_mode" {
  description = "Value of the pod ip allocation mode for the nodepool. This can be either DynamicIndividual or StaticBlock"
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

variable "aks_cli_config" {
  type = object({
    role                          = string
    aks_name                      = string
    sku_tier                      = string
    subnet_name                   = optional(string, null)
    managed_identity_name         = optional(string, null)
    kubernetes_version            = optional(string, null)
    aks_custom_headers            = optional(list(string), [])
    use_aks_preview_cli_extension = optional(bool, true)
    use_aks_preview_private_build = optional(bool, false)
    default_node_pool = object({
      name        = string
      node_count  = number
      vm_size     = string
      vm_set_type = optional(string, "VirtualMachineScaleSets")
    })
    extra_node_pool = optional(
      list(object({
        name        = string
        node_count  = number
        vm_size     = string
        vm_set_type = optional(string, "VirtualMachineScaleSets")
        optional_parameters = optional(list(object({
          name  = string
          value = string
        })), [])
    })), [])
    optional_parameters = optional(list(object({
      name  = string
      value = string
    })), [])
  })
}
