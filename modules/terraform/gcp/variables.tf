variable "json_input" {
  description = "value of the json input"
  type = object({
    project_id = string
    run_id     = string
    region     = string
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

  validation {
    condition     = length(var.scenario_name) <= 30
    error_message = "scenario_name should be within 30 characters"
  }
}

variable "scenario_type" {
  description = "value of the scenario type"
  type        = string
  default     = ""
}

variable "network_config_list" {
  type = list(object({
    role     = string
    vpc_name = string
    vpc_cidr = string
    subnets = list(object({
      name = string
      cidr = string
      secondary_ip_ranges = list(object({
        range_name    = string
        ip_cidr_range = string
      }))
    }))
    firewall_rules = list(object({
      name               = string
      direction          = string
      priority           = number
      source_ranges      = list(string)
      destination_ranges = list(string)
      source_tags        = list(string)
      target_tags        = list(string)
      allow = list(object({
        protocol = string
        ports    = list(string)
      }))
    }))
  }))
  description = "List of network configurations"

}

variable "gke_config_list" {
  type = list(object({
    role               = string
    name               = string
    vpc_name           = string
    subnet_name        = string
    kubernetes_version = optional(string)
    default_node_pool = object({
      name         = string
      node_count   = number
      machine_type = string
    })
    extra_node_pools = list(object({
      name         = string
      machine_type = string
      node_count   = number
    }))
  }))
  description = "List of GKE configurations"

}
