resource "azurerm_storage_account" "storage_account" {
  name                = var.storage_account_name
  resource_group_name = var.resource_group_name
  location            = var.location
  # Valid options are Standard and Premium. For BlockBlobStorage and FileStorage accounts only Premium is valid. Blobs with a tier of Premium are of account kind StorageV2
  account_tier = var.storage_account_tier
  # Valid options are BlobStorage, BlockBlobStorage, FileStorage, Storage and StorageV2
  account_kind             = var.storage_account_kind
  account_replication_type = var.storage_account_replication_type
  tags                     = var.tags
}
