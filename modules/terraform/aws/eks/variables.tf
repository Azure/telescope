variable "run_id" {
  description = "The run id for the load balancer."
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

variable "eks_config" {
  type = object({
    eks_name                = string
    vpc_name                = string
    policy_attachment_names = list(string)
    eks_managed_node_groups = list(object({
      name           = string
      ami_type       = string
      instance_types = list(string)
      min_size       = number
      max_size       = number
      desired_size   = number
      capacity_type  = optional(string, "ON_DEMAND")
      labels         = optional(map(string), {})
    }))
    eks_addons = list(object({
      name                    = string
      version                 = optional(string)
      service_account         = optional(string)
      policy_attachment_names = optional(list(string), [])
    }))
  })
}

################################################################################
# EKS Managed Node Group
################################################################################

# variable "eks_managed_node_groups" {
#   description = "Map of EKS managed node group definitions to create"
#   type        = any
#   default     = {}
# }

# variable "eks_managed_node_group_defaults" {
#   description = "Map of EKS managed node group default configurations"
#   type        = any
#   default     = {}
# }

# variable "min_size" {
#   description = "Minimum number of instances/nodes"
#   type        = number
#   default     = 0
# }

# variable "max_size" {
#   description = "Maximum number of instances/nodes"
#   type        = number
#   default     = 3
# }

# variable "desired_size" {
#   description = "Desired number of instances/nodes"
#   type        = number
#   default     = 1
# }

# variable "node_group_name" {
#   description = "Name of the EKS managed node group"
#   type        = string
#   default     = ""
# }

# variable "instance_types" {
#   description = "Set of instance types associated with the EKS Node Group. Defaults to `[\"t3.medium\"]`"
#   type        = list(string)
#   default     = null
# }

# variable "ami_type" {
#   description = "Type of Amazon Machine Image (AMI) associated with the EKS Node Group. See the [AWS documentation](https://docs.aws.amazon.com/eks/latest/APIReference/API_Nodegroup.html#AmazonEKS-Type-Nodegroup-amiType) for valid values"
#   type        = string
#   default     = null
# }
