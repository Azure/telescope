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

variable "k8s_machine_type" {
  description = "Value to replace EKS nodes instance_types"
  type        = string
  default     = null
}

variable "ena_express" {
  description = "Whether to enable ENA Express. This replaces the value under eks_managed_node_groups"
  type        = bool
  default     = null
}

variable "capacity_reservation_id" {
  description = "The capacity reservation ID. This replaces the value under eks_managed_node_groups"
  type        = string
  default     = null
}

variable "eks_config" {
  type = object({
    role                      = string
    eks_name                  = string
    enable_karpenter          = optional(bool, false)
    enable_cluster_autoscaler = optional(bool, false)
    vpc_name                  = string
    policy_arns               = list(string)
    auto_mode                 = optional(bool, false)
    node_pool_general_purpose = optional(bool, false)
    node_pool_system          = optional(bool, false)
    eks_managed_node_groups = list(object({
      name           = string
      ami_type       = string
      instance_types = list(string)
      min_size       = number
      max_size       = number
      desired_size   = number
      capacity_type  = optional(string, "ON_DEMAND")
      labels         = optional(map(string), {})
      subnet_names   = optional(list(string), null)
      ena_express    = optional(bool, null)
      taints = optional(list(object({
        key    = string
        value  = string
        effect = string
      })), [])
      block_device_mappings = optional(list(object({
        device_name = string
        ebs = object({
          delete_on_termination = optional(bool, true)
          iops                  = optional(number, null)
          throughput            = optional(number, null)
          volume_size           = optional(number, null)
          volume_type           = optional(string, null)
        })
      })), [])
      capacity_reservation_specification = optional(object({
        capacity_reservation_preference = optional(string)
        capacity_reservation_target = optional(object({
          capacity_reservation_id                 = optional(string)
          capacity_reservation_resource_group_arn = optional(string)
        }))
      }), null)
      instance_market_options = optional(object({
        market_type = optional(string)
        spot_options = optional(object({
          block_duration_minutes         = optional(number)
          instance_interruption_behavior = optional(string)
          max_price                      = optional(string)
          spot_instance_type             = optional(string)
          valid_until                    = optional(string)
        }))
      }), null)
      network_interfaces = optional(object({
        associate_public_ip_address = optional(bool)
        delete_on_termination       = optional(bool)
        interface_type              = optional(string)
      }), null)
    }))
    eks_addons = list(object({
      name            = string
      version         = optional(string)
      service_account = optional(string)
      policy_arns     = optional(list(string), [])
      configuration_values = optional(object({
        env = optional(map(string))
      }))
      vpc_cni_warm_prefix_target = optional(number, 1)
      before_compute             = optional(bool, false)
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

variable "user_data_path" {
  description = "The path to the user data file"
  type        = string
  default     = ""
}
