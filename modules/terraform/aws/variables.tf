variable "json_input" {
  description = "value of the json input"
  type = object({
    owner                     = string
    run_id                    = string
    region                    = string
    public_key_path           = string
    machine_type              = optional(string)
    user_data_path            = optional(string)
    data_disk_volume_type     = optional(string)
    data_disk_size_gb         = optional(number)
    data_disk_tier            = optional(string)
    data_disk_iops_read_only  = optional(number)
    data_disk_iops_read_write = optional(number)
    data_disk_mbps_read_only  = optional(number)
    data_disk_mbps_read_write = optional(number)
    data_disk_count           = optional(number)
    data_disk_attach          = optional(bool)
    ultra_ssd_enabled         = optional(bool)

    efs_performance_mode                = optional(string)
    efs_throughput_mode                 = optional(string)
    efs_provisioned_throughput_in_mibps = optional(number)
  })
}

variable "scenario_name" {
  description = "Name of the scenario"
  type        = string
  default     = ""
}

variable "scenario_type" {
  description = "value of the scenario type"
  type        = string
  default     = ""
}

variable "deletion_delay" {
  description = "Time duration after which the resources can be deleted (e.g., '1h', '2h', '4h')"
  type        = string
  default     = "2h"
}

variable "network_config_list" {
  description = "Configuration for creating the server network."
  type = list(object({
    role           = string
    vpc_name       = string
    vpc_cidr_block = string
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

variable "loadbalancer_config_list" {
  description = "List of Loadbalancer configurations"
  type = list(object({
    role               = string
    vpc_name           = string
    subnet_name        = string
    load_balancer_type = string
    is_internal_lb     = optional(bool, false)
    lb_target_group = list(object({
      role       = string
      tg_suffix  = string
      port       = number
      protocol   = string
      rule_count = number
      vpc_name   = string
      health_check = object({
        port                = number
        protocol            = string
        interval            = number
        timeout             = number
        healthy_threshold   = number
        unhealthy_threshold = number
      })
      lb_listener = object({
        port     = number
        protocol = string
      })
      lb_target_group_attachment = object({
        vm_name = string
        port    = number
      })
    }))
  }))
  default = []
}

variable "vm_config_list" {
  description = "List of configuration for virtual machines"
  type = list(object({
    vm_name                     = string
    zone_suffix                 = string
    role                        = string
    subnet_name                 = string
    security_group_name         = string
    associate_public_ip_address = bool

    ami_config = optional(object({
      most_recent         = bool
      name                = string
      virtualization_type = string
      architecture        = string
      owners              = list(string)
    }))
  }))
  default = []
}

variable "data_disk_config" {
  description = "List of data disks and disk associations with the same configuration to be created"
  type = object({
    zone_suffix = string
    vm_name     = string
  })
  default = null
}

variable "bucket_name_prefix" {
  description = "Value of the bucket name prefix"
  type        = string
  default     = ""
}

variable "eks_config_list" {
  type = list(object({
    role        = string
    eks_name    = string
    vpc_name    = string
    policy_arns = list(string)
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
    }))
  }))
  default = []
}

variable "efs_name_prefix" {
  description = "Value of the bucket name prefix"
  type        = string
  default     = ""
}

variable "private_link_conf" {
  description = "configuration for private link"
  type = object({
    service_lb_role = string

    client_vpc_name            = string
    client_subnet_name         = string
    client_security_group_name = string
  })
  default = null
}
