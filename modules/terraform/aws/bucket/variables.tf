variable "bucket_name_prefix" {
  description = "Value of the bucket name prefix"
  type        = string
  default     = ""
}

variable "run_id" {
  description = "Value of the run id"
  type        = string
  default     = ""
}

variable "tags" {
  type    = map(string)
  default = {}
}
