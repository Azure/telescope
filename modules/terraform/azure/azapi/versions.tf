terraform {
  required_version = ">=1.5.6"
  required_providers {
    azapi = {
      source  = "Azure/azapi"
      version = "2.8.0"
    }
    azurerm = {
      source = "hashicorp/azurerm"
    }
  }
}
