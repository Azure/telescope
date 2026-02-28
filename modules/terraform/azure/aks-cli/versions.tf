terraform {
  required_providers {
    azurerm = {
      source = "hashicorp/azurerm"
    }
    azapi = {
      source  = "Azure/azapi"
      version = "1.13.0"
    }
  }
}
