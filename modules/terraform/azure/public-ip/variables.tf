variable "resource_group_name" {
  description = "Value of the resource group name"
  type        = string
  default     = "cle-rg"
}

variable "location" {
  description = "Value of the location"
  type        = string
  default     = "East US"
}

variable "public_ip_names" {
  description = "A list of public IP names"
  type        = list(string)
  default     = ["client-pip", "server-pip"]
}

variable "tags" {
  type = map(string)
  default = {
  }
}
