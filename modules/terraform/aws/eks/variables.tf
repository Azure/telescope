variable "run_id" {
  description = "The run id for  eks cluster"
  type        = string
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

variable "region" {
  description = "value of the region"
  type        = string
  default     = "us-east-2"
}

variable "eks_config" {
  type = object({
    role             = string
    eks_name         = string
    enable_karpenter = optional(bool, false)
    vpc_name         = string
    policy_arns      = list(string)
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
    eks_addons = list(object({
      name            = string
      version         = optional(string)
      service_account = optional(string)
      policy_arns     = optional(list(string), [])
    }))
    kubernetes_version = optional(string, null)
  })
}
