variable "pg_config" {
  description = "Configuration for deployment of placement group"
  type = object({
    name           = string
    strategy       = string
    partition_count = optional(string)
    spread_level   = optional(string)
  })
}

variable "tags" {
  type    = map(string)
  default = {}
}