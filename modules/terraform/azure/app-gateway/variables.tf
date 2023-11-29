variable "subnet_id" {
  description = "Subnet ID"
  type        = string
  default     = ""
}
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

variable "subnet_id" {
  description = "Subnet ID"
  type        = string
  default     = ""
}

variable "appgateway_config" {
  description = "Configuration for the load balancer."
  type = object({
    role                  = string
    appgateway_name       = string
    public_ip_name        = string
    subnet_name           = string
  })
}