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

variable "bucket_source_path" {
  description = "Value of bucket source file path"
  type = string
  default = ""
}

variable "bucket_file_key" {
  description = "Value for bucket file key"
  type = string
  default = ""
}

variable "tags" {
  type    = map(string)
  default = {}
}
