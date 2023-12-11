locals {
  region                           = lookup(var.json_input, "region", "East US")
  machine_type                     = lookup(var.json_input, "machine_type", "Standard_D2ds_v5")
  accelerated_networking           = lookup(var.json_input, "accelerated_networking", true)
  run_id                           = lookup(var.json_input, "run_id", "123456")
  user_data_path                   = lookup(var.json_input, "user_data_path", "")
  data_disk_storage_account_type   = lookup(var.json_input, "data_disk_storage_account_type", "")
  data_disk_size_gb                = lookup(var.json_input, "data_disk_size_gb", "")
  data_disk_iops_read_write        = lookup(var.json_input, "data_disk_iops_read_write", null)
  data_disk_mbps_read_write        = lookup(var.json_input, "data_disk_mbps_read_write", null)
  ultra_ssd_enabled                = lookup(var.json_input, "ultra_ssd_enabled", false)
  data_disk_iops_read_only         = lookup(var.json_input, "data_disk_iops_read_only", null)
  data_disk_mbps_read_only         = lookup(var.json_input, "data_disk_mbps_read_only", null)
  data_disk_tier                   = lookup(var.json_input, "data_disk_tier", null)
  data_disk_caching                = lookup(var.json_input, "data_disk_caching", "ReadOnly")
  storage_account_tier             = lookup(var.json_input, "storage_account_tier", "")
  storage_account_kind             = lookup(var.json_input, "storage_account_kind", "")
  storage_account_replication_type = lookup(var.json_input, "storage_account_replication_type", "")

  tags = {
    "owner"             = lookup(var.json_input, "owner", "github_actions")
    "scenario"          = "${var.scenario_type}-${var.scenario_name}"
    "creation_time"     = timestamp()
    "deletion_due_time" = timeadd(timestamp(), var.deletion_delay)
    "run_id"            = local.run_id
  }

  network_config_map                     = { for network in var.network_config_list : network.role => network }
  loadbalancer_config_map                = { for loadbalancer in var.loadbalancer_config_list : loadbalancer.role => loadbalancer }
  appgateway_config_map                  = { for appgateway in var.appgateway_config_list : appgateway.role => appgateway }
  aks_config_map                         = { for aks in var.aks_config_list : aks.role => aks }
  vm_config_map                          = { for vm in var.vm_config_list : vm.vm_name => vm }
  vmss_config_map                        = { for vmss in var.vmss_config_list : vmss.vmss_name => vmss }
  nic_backend_pool_association_map       = { for config in var.nic_backend_pool_association_list : config.nic_name => config }
  all_nics                               = merge([for network in var.network_config_list : module.virtual_network[network.role].nics]...)
  all_subnets                            = merge([for network in var.network_config_list : module.virtual_network[network.role].subnets]...)
  all_loadbalancer_backend_address_pools = { for key, lb in module.load_balancer : "${key}-lb-pool" => lb.lb_pool_id }
  disk_association_map                   = { for config in var.data_disk_association_list : config.vm_name => config }
  all_vms                                = { for vm in var.vm_config_list : vm.vm_name => module.virtual_machine[vm.vm_name].vm }
  data_disk_config_map                   = { for config in var.data_disk_config_list : config.disk_name => config }
  all_data_disks                         = { for disk in var.data_disk_config_list : disk.disk_name => module.data_disk[disk.disk_name].data_disk }
}

provider "azurerm" {
  features {}
}

resource "tls_private_key" "admin-ssh-key" {
  algorithm = "RSA"
  rsa_bits  = 2048
}

module "resource_group" {
  source              = "./resource-group"
  resource_group_name = local.run_id
  location            = local.region
  tags                = local.tags
}

module "public_ips" {
  source              = "./public-ip"
  resource_group_name = module.resource_group.name
  location            = local.region
  public_ip_names     = var.public_ip_names
  tags                = local.tags
}

module "virtual_network" {
  for_each = local.network_config_map

  source                 = "./network"
  network_config         = each.value
  resource_group_name    = module.resource_group.name
  location               = local.region
  accelerated_networking = local.accelerated_networking
  public_ips             = module.public_ips.pip_ids
  tags                   = local.tags
}

module "aks" {
  for_each = local.aks_config_map

  source              = "./aks"
  resource_group_name = module.resource_group.name
  location            = local.region
  vm_sku              = local.machine_type
  subnet_id           = local.all_subnets[each.value.subnet_name]
  aks_config          = each.value
  tags                = local.tags
}

module "load_balancer" {
  for_each = local.loadbalancer_config_map

  source              = "./load-balancer"
  resource_group_name = module.resource_group.name
  location            = local.region
  loadbalancer_config = each.value
  public_ip_id        = module.public_ips.pip_ids[each.value.public_ip_name]
  tags                = local.tags
}

module "appgateway" {
  for_each = local.appgateway_config_map

  source              = "./app-gateway"
  appgateway_config   = each.value
  resource_group_name = module.resource_group.name
  location            = local.region
  subnet_id           = local.all_subnets[each.value.subnet_name]
  public_ip_id        = module.public_ips.pip_ids[each.value.public_ip_name]
  tags                = local.tags
}

module "data_disk" {
  for_each = local.data_disk_config_map

  source                         = "./data-disk"
  resource_group_name            = module.resource_group.name
  location                       = local.region
  data_disk_name                 = each.value.disk_name
  tags                           = local.tags
  data_disk_storage_account_type = local.data_disk_storage_account_type
  data_disk_size_gb              = local.data_disk_size_gb
  data_disk_iops_read_write      = local.data_disk_iops_read_write
  data_disk_mbps_read_write      = local.data_disk_mbps_read_write
  data_disk_iops_read_only       = local.data_disk_iops_read_only
  data_disk_mbps_read_only       = local.data_disk_mbps_read_only
  data_disk_tier                 = local.data_disk_tier
  zone                           = each.value.zone
}

module "virtual_machine" {
  for_each = local.vm_config_map

  source              = "./virtual-machine"
  name                = each.value.vm_name
  resource_group_name = module.resource_group.name
  location            = local.region
  vm_sku              = local.machine_type
  nic                 = local.all_nics[each.value.nic_name]
  vm_config           = each.value
  public_key          = tls_private_key.admin-ssh-key.public_key_openssh
  user_data_path      = local.user_data_path
  tags                = local.tags
  ultra_ssd_enabled   = local.ultra_ssd_enabled
}

module "virtual_machine_scale_set" {
  for_each = local.vmss_config_map

  source                = "./virtual-machine-scale-set"
  name                  = each.value.vmss_name
  resource_group_name   = module.resource_group.name
  location              = local.region
  vm_sku                = local.machine_type
  subnet_id             = local.all_subnets[each.value.subnet_name]
  lb_pool_id            = local.all_loadbalancer_backend_address_pools[each.value.loadbalancer_pool_name]
  ip_configuration_name = each.value.ip_configuration_name
  vmss_config           = each.value
  public_key            = tls_private_key.admin-ssh-key.public_key_openssh
  user_data_path        = local.user_data_path
  tags                  = local.tags
}

resource "azurerm_network_interface_backend_address_pool_association" "nic-backend-pool-association" {
  for_each = local.nic_backend_pool_association_map

  network_interface_id    = local.all_nics[each.key]
  ip_configuration_name   = each.value.ip_configuration_name
  backend_address_pool_id = local.all_loadbalancer_backend_address_pools[each.value.backend_pool_name]
}

resource "azurerm_virtual_machine_data_disk_attachment" "disk-association" {
  for_each = local.disk_association_map

  managed_disk_id    = local.all_data_disks[each.value.data_disk_name].id
  virtual_machine_id = local.all_vms[each.key].id
  lun                = 0
  caching            = (local.data_disk_caching == null || local.data_disk_caching == "") ? "ReadOnly" : local.data_disk_caching
}

resource "local_file" "ssh-private-key" {
  content         = tls_private_key.admin-ssh-key.private_key_pem
  filename        = "${path.module}/private_key.pem"
  file_permission = "0600"
}

resource "random_string" "storage_account_random_suffix" {
  count            = var.storage_account_name_prefix != null ? 1 : 0
  length           = 8
  special          = false
  upper            = false
  numeric          = true
  override_special = "_-"
}


module "storage_account" {
  source = "./storage-account"

  count                            = var.storage_account_name_prefix != null ? 1 : 0
  storage_account_name             = "${var.storage_account_name_prefix}${random_string.storage_account_random_suffix[0].result}"
  resource_group_name              = module.resource_group.name
  location                         = local.region
  storage_account_tier             = local.storage_account_tier
  storage_account_kind             = local.storage_account_kind
  storage_account_replication_type = local.storage_account_replication_type
  tags                             = local.tags
}
