variable "name_prefix" {
  description = "Prefix for the lb-rule name."
  type        = string
}

variable "type" {
  description = "Load Balancer Rule Type."
  type        = string
  default     = "Inbound"
}

variable "frontend_port" {
  description = "value for frontend_port."
  type        = number
}

variable "backend_port" {
  description = "value for backend_port."
  type        = number
}

variable "lb_id" {
  description = "ID of the Azure Load Balancer."
  type        = string
}

variable "lb_pool_id" {
  description = "ID of the Azure Load Balancer Backend Address Pool."
  type        = string
}

variable "probe_id" {
  description = "ID of the Azure Load Balancer Probe."
  type        = string
}

variable "protocol" {
  description = "value for protocol."
  type        = string
  default     = "Tcp"
}

variable "rule_count" {
  description = "Number of rules to create."
  type        = number
  default     = 1
}

variable "enable_tcp_reset" {
  description = "value for enable_tcp_reset."
  type        = bool
  default     = true
}

variable "idle_timeout_in_minutes" {
  description = "value for idle_timeout_in_minutes."
  type        = number
  default     = 4
}

variable "frontend_ip_config_name_prefix" {
  description = "value for frontend_ip_configuration_name prefix."
  type        = string
  default     = "ingress"
}
