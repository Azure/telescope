variable "vm_config" {
  description = "Configuration for virtual machine"
  type = object({
    vm_name                     = string
    name_prefix                 = string
    subnet_name                 = string
    security_group_name         = string
    associate_public_ip_address = bool
  })
}

variable "user_data_path" {
  description = "value of the user data path"
  type        = string
}

variable "instance_type" {
  description = "value of instance type"
  type        = string
  default     = "m5.4xlarge"
}

variable "job_id" {
  description = "Value of the job id"
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
