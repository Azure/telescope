variable "zone" {
  description = "Value of the availability zone"
  type        = string
  default     = null
}

variable "tags" {
  type = map(string)
  default = {
  }
}

variable "data_disk_size_gb" {
  description = "Value of the disk_size_gb"
  type        = string
  default     = ""
}

variable "data_disk_volume_type" {
  description = "Value of the volume type"
  type        = string
  default     = ""
}

variable "data_disk_iops_read_write" {
  description = "Value of the disk_iops_read_write"
  type        = number
  default     = null
}

variable "data_disk_mbps_read_write" {
  description = "Value of the disk_mbps_read_write"
  type        = number
  default     = null
}
