variable "run_id" {
  description = "The run id for  eks cluster"
  type        = string
}

variable "tags" {
  type = map(string)
  default = {
  }
}
variable "vpc_id" {
  description = "The vpc ID"
  type        = string
  default     = ""
}

variable "region" {
  description = "value of the region"
  type        = string
  default     = "us-east-2"
}

variable "eks_config" {
  type = object({
    role                      = string
    eks_name                  = string
    enable_karpenter          = optional(bool, false)
    enable_cluster_autoscaler = optional(bool, false)
    vpc_name                  = string
    policy_arns               = list(string)
    eks_managed_node_groups = list(object({
      name           = string
      ami_type       = string
      instance_types = list(string)
      min_size       = number
      max_size       = number
      desired_size   = number
      capacity_type  = optional(string, "ON_DEMAND")
      labels         = optional(map(string), {})
      taints = optional(list(object({
        key    = string
        value  = string
        effect = string
      })), [])
    }))
    eks_addons = list(object({
      name            = string
      version         = optional(string)
      service_account = optional(string)
      policy_arns     = optional(list(string), [])
      configuration_values = optional(object({
        env = optional(map(string))
      }))
    }))
    kubernetes_version = optional(string, null)
    auto_scaler_profile = optional(object({
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
    }))
    enable_cni_metrics_helper = optional(bool, false)
  })
}
