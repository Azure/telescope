resource "azurerm_storage_account" "storage_account" {
  name                = var.storage_account_name
  resource_group_name = var.resource_group_name
  location            = var.location
  # Valid options are Standard and Premium. For BlockBlobStorage and FileStorage accounts only Premium is valid. Blobs with a tier of Premium are of account kind StorageV2
  account_tier = var.storage_account_tier
  # Valid options are BlobStorage, BlockBlobStorage, FileStorage, Storage and StorageV2
  account_kind              = var.storage_account_kind
  account_replication_type  = var.storage_account_replication_type
  enable_https_traffic_only = var.enable_https_traffic_only

  tags = var.tags
}

resource "azurerm_storage_share" "fileshare" {
  count                = var.storage_share_config == null ? 0 : 1
  name                 = var.storage_share_config.name
  storage_account_name = azurerm_storage_account.storage_account.name
  quota                = var.storage_share_config.quota
  access_tier          = var.storage_share_config.access_tier
  enabled_protocol     = var.storage_share_config.enabled_protocol
}

resource "azurerm_storage_container" "example" {
  count                 = var.storage_blob_config == null ? 0 : 1
  name                  = var.storage_blob_config.container_name
  storage_account_name  = azurerm_storage_account.storage_account.name
  container_access_type = "private"
}

resource "azurerm_storage_blob" "blob" {
  count                  = var.storage_blob_config == null ? 0 : 1
  name                   = var.storage_blob_config.blob_name
  storage_account_name   = azurerm_storage_account.storage_account.name
  storage_container_name = var.storage_blob_config.container_name
  type                   = "Block"
  source                 = var.storage_blob_config.source_file_path
}