
resource "azurerm_managed_disk" "data_disk" {
  name                 = var.data_disk_name
  location             = var.location
  resource_group_name  = var.resource_group_name
  storage_account_type = var.data_disk_storage_account_type
  create_option        = "Empty"
  disk_size_gb         = var.data_disk_size_gb
  tags                 = var.tags
  disk_iops_read_write = var.data_disk_iops_read_write
  disk_mbps_read_write = var.data_disk_mbps_read_write
  disk_iops_read_only  = var.data_disk_iops_read_only
  disk_mbps_read_only  = var.data_disk_mbps_read_only
  tier                 = var.data_disk_tier
  zone                 = var.zone
}


