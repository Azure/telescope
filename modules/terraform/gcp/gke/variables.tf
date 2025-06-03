variable "gke_config" {
  type = object({
    role               = string
    name               = string
    vpc_name           = string
    subnet_name        = string
    kubernetes_version = optional(string)
    default_node_pool = object({
      name         = string
      node_count   = number
      machine_type = string
    })
    extra_node_pools = list(object({
      name         = string
      machine_type = string
      node_count   = number
    }))
  })
}

variable "subnet_id" {
  type        = string
  description = "Subnet ID"
}

variable "vpc_id" {
  type        = string
  description = "VPC ID"
}

variable "labels" {
  type        = map(string)
  description = "Labels to apply to all resources"
}

variable "run_id" {
  type        = string
  description = "Unique identifier for the run"
}
