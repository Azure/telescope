terraform {
  required_version = ">=1.5.6"
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "<= 5.0.1"
    }
    azapi = {
      source  = "Azure/azapi"
      version = "2.8.0"
    }
  }
}
