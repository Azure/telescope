variable "deployment_name" {
  description = "Name of the deployment"
  type        = string
}

variable "resource_group_name" {
  description = "Value of the resource group name"
  type        = string
}

variable "parameters_path" {
  description = "Path to the parameters file"
  type        = string
}

variable "location" {
  description = "Azure region to deploy the resources"
  type        = string
}

variable "tags" {
  type = map(string)
  default = {
  }
}

