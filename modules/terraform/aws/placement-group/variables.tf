variable "placement_group_config" {
  description = "Configuration for deployment of placement group"
  type = object({
    name            = string
    strategy        = string
    partition_count = optional(string)
    spread_level    = optional(string)
  })
}

variable "pg_name" {
  description = "Dynamically created name for placement group"
  type        = string
  default     = ""
}

variable "tags" {
  type    = map(string)
  default = {}
}