variable "resource_group_name" {
  description = "Value of the resource group name"
  type        = string
  default     = "agc-resgp"
}

variable "location" {
  description = "Value of the location"
  type        = string
  default     = "East US"
}

variable "tags" {
  type = map(string)
  default = {
  }
}

variable "association_subnet_id" {
  description = "Subnet ID where association should be deployed."
  type        = string
}

variable "aks_cluster_oidc_issuer" {
  description = "The issuer URL for the cluster."
  type        = string
}

variable "agc_config" {
  description = "Configuration for AGC."
  type = object({
    role                    = string
    name                    = string
    frontends               = list(string)
    association_subnet_name = string
  })
}