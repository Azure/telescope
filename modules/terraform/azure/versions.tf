terraform {
  required_version = ">=1.5.6"
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "<= 4.18.0"
    }
  }
}
