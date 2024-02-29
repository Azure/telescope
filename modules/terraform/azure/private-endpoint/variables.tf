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


variable "psc_config" {
  description = "Configuration for the private endpoint using a storage account"
  type = object({
    name                           = var.pe_name
    private_connection_resource_id = var.storage_account_name
    is_manual_connection           = false
    subresource_names = ["blob"]
  })
}
