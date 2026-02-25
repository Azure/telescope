terraform {
  required_version = ">=1.5.6"
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = ">= 4.42.0, != 4.42.0, < 5.0.0"
    }

    # Used for ARM child resources not yet supported by AzureRM (e.g., ACR artifact cache rules).
    azapi = {
      source  = "Azure/azapi"
      version = ">= 2.0.0, < 3.0.0"
    }
  }
}
