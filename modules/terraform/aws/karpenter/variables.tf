variable "karpenter_config" {
  type = object({
    cluster_name        = string
    eks_cluster_version = string
    vpc_cidr            = string
    eks_managed_node_group = object({
      name           = string
      instance_types = list(string)
      min_size       = number
      max_size       = number
      desired_size   = number
      capacity_type  = string
    })
    karpenter_chart_version = string
  })
}


variable "json_input" {
  description = "value of the json input"
  type = object({
    run_id = string
    region = string
  })
}

variable "owner" {
  description = "Owner of the scenario"
  type        = string
  default     = "azure_devops"
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
