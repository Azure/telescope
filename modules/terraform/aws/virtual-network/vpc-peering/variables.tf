variable "tags" {
  description = "A map of tags to add to all resources"
  type        = map(string)
  default     = {}
}

variable "run_id" {
  description = "Run ID of the current deployment"
  type = string
  default = ""
}

variable "peer_region" {
  description = "Run ID of the current deployment"
  type = string
  default = ""
}