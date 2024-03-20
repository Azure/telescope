variable "pe_name" {
  description = "Value of the private endpoint name"
  type        = string
  default     = "pe"
}


variable "location" {
  description = "Location of private endpoint"
  type        = string
  default     = "East US"
}


variable "resource_group_name" {
  description = "Value of the resource group name"
  type        = string
  default     = "rg"
}


variable "pe_subnet_id" {
  description = "ID of the private endpoint's subnet"
  type        = string
  default     = ""
}

variable "resource_id" {
  description = "private service connection resource id"
  type        = string
  default     = ""
}

variable "storage_account_name" {
  description = "storage account name"
  type        = string
  default     = "0003plssinglevm"
}

variable "tags" {
  type = map(string)
  default = {
  }
}