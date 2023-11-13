variable "region" {
  description = "Value of the region"
  type        = string
  default     = "us-east-1"
}

variable "az" {
  description = "Value of the availability zone"
  type        = string
  default     = "us-east-1b"
}

variable "instance_type" {
  description = "Value of the instance type"
  type        = string
  default     = "m5.4xlarge"
}

variable "job_id" {
  description = "Value of the job id"
  type        = string
  default     = ""
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
}

variable "network_config_list" {
  description = "Configuration for creating the server network."
  type = list(object({
    name_prefix            = string
    vpc_name               = string
    vpc_cidr_block         = string
    subnet_names           = list(string)
    subnet_cidr_block      = list(string)
    security_group_name    = string
    route_table_cidr_block = string
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
}

variable "loadbalancer_config_list" {
  description = "List of Loadbalancer configurations"
  type = list(object({
    name_prefix        = string
    vpc_name           = string
    subnet_name        = string
    load_balancer_type = string
    lb_target_group = list(object({
      name_prefix = string
      tg_suffix   = string
      port        = number
      protocol    = string
      rule_count  = number
      vpc_name    = string
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
}

variable "vm_config_list" {
  description = "List of configuration for virtual machines"
  type = list(object({
    vm_name                     = string
    name_prefix                 = string
    subnet_name                 = string
    security_group_name         = string
    associate_public_ip_address = bool
  }))
}
