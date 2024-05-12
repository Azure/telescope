
variable "resource_group_name" {
  type        = string
  description = "The name of the resource group"
}

variable "template_file_path" {
  description = "Path to the ARM template file"
  default     = "template.json"
}

variable "parameters_file_path" {
  description = "Path to the ARM template parameters file"
  default     = "parameters.json"
}

variable "deployment_mode" {
  description = "The deployment mode of the template deployment"
  default     = "Incremental"
}

variable "deployment_name" {
  description = "The name of the deployment"
  default     = "example-deployment"
}