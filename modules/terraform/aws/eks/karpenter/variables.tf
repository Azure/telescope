variable "region" {
  type        = string
  description = "value of the region"
}

variable "cluster_name" {
  type        = string
  description = "value of the cluster name"
}

variable "cluster_endpoint" {
  type        = string
  description = "value of the cluster endpoint"
}

variable "tags" {
  type        = map(string)
  description = "value of the tags"
}

variable "user_data_path" {
  type        = string
  description = "value of the user data path"
  default     = ""
}

variable "oidc_provider_arn" {
  type        = string
  description = "value of the oidc provider arn"

}

variable "run_id" {
  type        = string
  description = "The run id for  eks cluster"
}

variable "cluster_iam_role_name" {
  type        = string
  description = "value of the cluster iam role name"

}

variable "karpenter_namespace" {
  type = string
  description = "value of the karpenter namespace"
}