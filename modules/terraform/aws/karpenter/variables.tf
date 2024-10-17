variable "karpenter_config" {
  type = object({
    cluster_name        = string
    eks_cluster_version = string
    vpc_cidr            = string
    eks_managed_node_group = object({
      name           = string
      instance_types = list(string)
      min_size       = number
      max_size       = number
      desired_size   = number
      capacity_type  = string
    })
    karpenter_chart_version = string
  })
}


variable "json_input" {
  description = "value of the json input"
  type = object({
    run_id = string
    region = string
  })
}
