variable "region" {
  type        = string
  description = "value of the region"
}

variable "cluster_name" {
  type        = string
  description = "value of the cluster name"
}

variable "tags" {
  type        = map(string)
  description = "value of the tags"
}

variable "oidc_provider_arn" {
  type        = string
  description = "ARN of the OIDC provider for IRSA"
}

variable "cluster_version" {
  type        = string
  description = "value of the cluster version"
}

variable "auto_scaler_profile" {
  type = object({
    balance_similar_node_groups      = optional(bool, false)
    expander                         = optional(string, "random")
    max_graceful_termination_sec     = optional(string, "600")
    max_node_provision_time          = optional(string, "15m")
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
  })
  description = "value of the auto scaler profile"
}
