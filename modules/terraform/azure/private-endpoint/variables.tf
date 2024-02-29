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


variable "psc_name" {
  description = "name of the private service connection"
  type        = string
  default     = ""
}
