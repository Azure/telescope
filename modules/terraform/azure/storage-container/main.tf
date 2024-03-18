# create anonymous access storage container

resource "azurerm_storage_container" "storage_container" {
  name                  = var.container_name
  storage_account_name  = var.storage_account_name
  container_access_type = "container"
}