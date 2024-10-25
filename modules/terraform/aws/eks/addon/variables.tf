variable "cluster_name" {
  description = "value of the EKS cluster name"
  type        = string
}

variable "cluster_oidc_provider_url" {
  description = "value of the EKS cluster OIDC provider URL"
  type        = string
}

variable "eks_addon_config_map" {
  description = "A map of EKS addons to deploy"
  type = map(object({
    name                 = string
    version              = optional(string)
    service_account      = optional(string)
    policy_arns          = optional(list(string), [])
    configuration_values = optional(string)
  }))
}
