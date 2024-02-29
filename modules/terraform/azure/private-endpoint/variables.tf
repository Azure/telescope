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


variable "private_service_connection" {
  description = "Configuration for the private endpoint using a storage account"
  type = object({
    name                           = string
    private_connection_resource_id = string
    is_manual_connection           = bool
    subresource_names              = list(string)
  })
}
