variable "resource_group_name" {
  description = "Value of the resource group name"
  type        = string
  default     = "rg"
}

variable "location" {
  description = "Value of the location"
  type        = string
  default     = "East US"
}

variable "data_disk_name" {
  description = "A list of data_disk names"
  type        = string
  default     = ""
}

variable "data_disk_storage_account_type" {
  description = "Value of the storage_account_type"
  type        = string
  default     = ""
}

variable "data_disk_size_gb" {
  description = "Value of the disk_size_gb"
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

variable "data_disk_iops_read_only" {
  description = "Value of the isk_iops_read_only"
  type        = number
  default     = null
}

variable "data_disk_mbps_read_only" {
  description = "Value of the disk_mbps_read_only"
  type        = number
  default     = null
}

variable "data_disk_tier" {
  description = "Value of the tier"
  type        = string
  default     = null
}

variable "tags" {
  type = map(string)
  default = {
  }
}

variable "zone" {
  description = "Value of the availability zone"
  type        = number
  default     = null
}
