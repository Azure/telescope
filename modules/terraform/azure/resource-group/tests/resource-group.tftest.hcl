provider "azurerm" {
  features {}
}
# Apply run block to create the resource group
run "create_resource_group" {
  command = plan
  variables {
   resource_group_name = "azure-rg-unit-test"
    location            = "eastus"
    tags                = {
      owner = "github_actions"
    }
  }
 
  # Check that the resource group name is correct
  assert {
    condition     = azurerm_resource_group.rg.name == "azure-rg-unit-test"
    error_message = "Invalid resource group name"
  }

  # Check that the resource group location is correct
  assert {
    condition     = azurerm_resource_group.rg.location == "eastus"
    error_message = "Invalid resource group location"
  }

  # Check that the resource group tags are correct
  assert {
    condition     = azurerm_resource_group.rg.tags.owner == "github_actions"
    error_message = "Invalid resource group tags"
  }
}