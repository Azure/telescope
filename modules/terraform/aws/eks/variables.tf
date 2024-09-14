variable "run_id" {
  description = "The run id for  eks cluster"
  type        = string
}

variable "user_data_path" {
  description = "value of the user data path"
  type        = string
  default     = ""
}

variable "tags" {
  type = map(string)
  default = {
  }
}
variable "vpc_id" {
  description = "The vpc ID"
  type        = string
  default     = ""
}

variable "eks_config" {
  type = object({
    role                              = string
    eks_name                          = string
    override_cluster_name             = optional(bool, false)
    vpc_name                          = string
    policy_arns                       = list(string)
    cloudformation_template_file_name = optional(string, null)
    install_karpenter                 = optional(bool, false)
    eks_managed_node_groups = list(object({
      name           = string
      ami_type       = string
      instance_types = list(string)
      min_size       = number
      max_size       = number
      desired_size   = number
      capacity_type  = optional(string, "ON_DEMAND")
      labels         = optional(map(string), {})
      taints = optional(list(object({
        key    = string
        value  = string
        effect = string
      })), [])
    }))
    pod_associations = optional(object({
      namespace            = string
      service_account_name = string
      role_arn_name        = string
    }))
    eks_addons = list(object({
      name            = string
      version         = optional(string)
      service_account = optional(string)
      policy_arns     = optional(list(string), [])
    }))
  })
}
