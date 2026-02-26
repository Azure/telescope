terraform {
  required_version = ">= 1.5.6"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "<= 4.42.0"
    }

    azapi = {
      source  = "Azure/azapi"
      version = "1.13.0"
    }
  }
}
