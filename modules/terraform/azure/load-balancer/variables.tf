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

variable "pip_id" {
  description = "ID of the public ip"
  type        = string
  default     = ""
}

variable "loadbalancer_config" {
  description = "Configuration for the load balancer."
  type = object({
    role                  = string
    loadbalance_name      = string
    public_ip_name        = string
    loadbalance_pool_name = string
    probe_protocol        = string
    probe_port            = number
    probe_request_path    = string
    lb_rules = list(object({
      type                    = string
      role                    = string
      frontend_port           = number
      backend_port            = number
      protocol                = string
      rule_count              = number
      enable_tcp_reset        = bool
      idle_timeout_in_minutes = number
    }))
  })
}

variable "public_ip_id" {
  description = "Value of the public IP id"
  type        = string
  default     = null
}

variable "tags" {
  type = map(string)
  default = {
  }
}
