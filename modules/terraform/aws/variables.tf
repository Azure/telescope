variable "json_input" {
  description = "value of the json input"
  type = object({
    run_id           = string
    region           = string
    creation_time    = string
    user_data_path   = optional(string, "")
    k8s_machine_type = optional(string, null)
  })

  validation {
    condition     = can(formatdate("", var.json_input.creation_time))
    error_message = "The creation_time value must be a valid rfc3339 format string (e.g.: '2024-10-17T18:30:42Z')"
  }

  validation {
    condition     = timecmp(var.json_input.creation_time, timeadd(plantimestamp(), "+1h")) < 0
    error_message = "The creation_time must not be more than 1 hour from now (${plantimestamp()})"
  }
}

variable "owner" {
  description = "Owner of the scenario"
  type        = string
}

variable "scenario_name" {
  description = "Name of the scenario"
  type        = string

  validation {
    condition     = length(var.scenario_name) <= 30
    error_message = "scenario_name should be within 30 characters"
  }
}

variable "scenario_type" {
  description = "value of the scenario type"
  type        = string
}

variable "deletion_delay" {
  description = "Time duration after which the resources can be deleted (e.g., '1h', '2h', '4h')"
  type        = string
  default     = "2h"

  validation {
    condition     = timecmp(timeadd(plantimestamp(), var.deletion_delay), timeadd(plantimestamp(), "+72h")) <= 0
    error_message = "The deletion_delay must not be more than 3 days (72h)"
  }
}

variable "network_config_list" {
  description = "Configuration for creating the server network."
  type = list(object({
    role                       = string
    vpc_name                   = string
    vpc_cidr_block             = string
    secondary_ipv4_cidr_blocks = optional(list(string))
    subnet = list(object({
      name                    = string
      cidr_block              = string
      zone_suffix             = string
      map_public_ip_on_launch = optional(bool, false)
    }))
    security_group_name = string
    route_tables = list(object({
      name             = string
      cidr_block       = string
      nat_gateway_name = optional(string)
    }))
    route_table_associations = list(object({
      name             = string
      subnet_name      = string
      route_table_name = string
    }))
    nat_gateway_public_ips = optional(list(object({
      name = string
    })))
    nat_gateways = optional(list(object({
      name           = string
      public_ip_name = string
      subnet_name    = string
    })))
    sg_rules = object({
      ingress = list(object({
        from_port  = number
        to_port    = number
        protocol   = string
        cidr_block = string
      })),
      egress = list(object({
        from_port  = number
        to_port    = number
        protocol   = string
        cidr_block = string
      }))
    })
  }))
  default = []
}

variable "eks_config_list" {
  type = list(object({
    role                      = string
    eks_name                  = string
    vpc_name                  = string
    policy_arns               = list(string)
    enable_karpenter          = optional(bool, false)
    enable_cluster_autoscaler = optional(bool, false)
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
      ena_express    = optional(bool, false)
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
  }))
  default = []
}
