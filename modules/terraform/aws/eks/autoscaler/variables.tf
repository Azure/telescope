variable "region" {
  type        = string
  description = "value of the region"
}

variable "cluster_name" {
  type        = string
  description = "value of the cluster name"
}

variable "tags" {
  type        = map(string)
  description = "value of the tags"
}

variable "cluster_iam_role_name" {
  type        = string
  description = "value of the cluster iam role name"
}

variable "cluster_version" {
  type        = string
  description = "value of the cluster version"
}
