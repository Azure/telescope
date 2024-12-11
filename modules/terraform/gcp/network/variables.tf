variable "network_config" {
  type = object({
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
  })
  description = "Network configuration"

  validation {
    condition     = length(var.network_config.vpc_name) >= 1 && length(var.network_config.vpc_name) <= 63 && can(regex("^[a-z]([-a-z0-9]*[a-z0-9])?", var.network_config.vpc_name))
    error_message = "VPC name must be between 1 and 63 characters long and match the regular expression [a-z]([-a-z0-9]*[a-z0-9])?"
  }

  validation {
    condition     = alltrue([for subnet in var.network_config.subnets : length(subnet.name) >= 1 && length(subnet.name) <= 63 && can(regex("^[a-z]([-a-z0-9]*[a-z0-9])?", subnet.name))])
    error_message = "Subnet name must be between 1 and 63 characters long and match the regular expression [a-z]([-a-z0-9]*[a-z0-9])?"
  }

}

variable "run_id" {
  type        = string
  description = "Unique identifier for the run"
}
