variable "bucket_name_prefix" {
  description = "Value of the bucket name prefix"
  type        = string
  default     = ""
}

variable "bucket_object_config" {
  description = "Configuration for deployment of bucket object with bucket"
  type = object({
    bucket_source_path = string
    bucket_file_key    = string
  })
  default = null
}

variable "local_path" {
  description = "Local path for bucket object to be uploaded"
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
