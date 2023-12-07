variable "vm_config" {
  description = "Configuration for virtual machine"
  type = object({
    vm_name                     = string
    name_prefix                 = string
    subnet_name                 = string
    security_group_name         = string
    associate_public_ip_address = bool

    data_disk_config = optional(object({
      data_disk_size_gb         = number
      data_disk_volume_type     = string
      data_disk_iops_read_write = optional(number)
      data_disk_mbps_read_write = optional(number)
    }))
  })
}

variable "user_data_path" {
  description = "value of the user data path"
  type        = string
}

variable "machine_type" {
  description = "value of instance type"
  type        = string
  default     = "m5.4xlarge"
}

variable "run_id" {
  description = "Value of the run id"
  type        = string
  default     = "123456"
}

variable "admin_key_pair_name" {
  description = "Name of the admin key pair"
  type        = string
  default     = "admin-key-pair"
}

variable "tags" {
  type    = map(string)
  default = {}
}

variable "zone" {
  description = "value of availability zone"
  type        = string
}
