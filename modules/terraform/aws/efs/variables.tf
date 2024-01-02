variable "efs_name_prefix" {
  description = "Value of the bucket name prefix"
  type        = string
  default     = ""
}

variable "run_id" {
  description = "Value of the run id"
  type        = string
  default     = ""
}

variable "performance_mode" {
  description = "The file system performance mode. Can be either 'generalPurpose' or 'maxIO'"
  type        = string
  default     = "generalPurpose"
}

variable "throughput_mode" {
  description = "Throughput mode for the file system. Can be bursting, provisioned, or elastic.Defaults to 'bursting'"
  type        = string
  default     = "bursting"
}

variable "provisioned_throughput_in_mibps" {
  description = "The throughput, measured in MiB/s, that you want to provision for the file system. Only applicable with throughput_mode set to provisioned."
  type        = number
  default     = null
}

variable "tags" {
  type    = map(string)
  default = {}
}
