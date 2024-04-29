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

variable "tags" {
  type = map(string)
  default = {
  }
}

variable "subnet_id" {
  description = "Subnet ID"
  type        = string
  default     = ""
}

variable "appgateway_config" {
  description = "Configuration for the load balancer."
  type = object({
    role            = string
    appgateway_name = string
    public_ip_name  = string
    subnet_name     = string
    appgateway_probes = list(object({
      name     = string
      protocol = string
    }))
    appgateway_backend_address_pool = list(object({
      name         = string
      ip_addresses = list(string)
    }))
    appgateway_frontend_ports = list(object({
      name = string
      port = string
    }))
    appgateway_backend_http_settings = list(object({
      name                  = string
      host_name             = string
      cookie_based_affinity = string
      port                  = number
      protocol              = string
      request_timeout       = number
      probe_name            = string
    }))
    appgateway_http_listeners = list(object({
      name                           = string
      frontend_ip_configuration_name = string
      frontend_port_name             = string
      protocol                       = string
      host_name                      = string
    }))
    appgateway_request_routing_rules = list(object({
      name                       = string
      priority                   = number
      rule_type                  = string
      http_listener_name         = string
      backend_address_pool_name  = string
      backend_http_settings_name = string
    }))
  })
}

variable "public_ip_id" {
  description = "Value of the public IP id"
  type        = string
  default     = null
}
