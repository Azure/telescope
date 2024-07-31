locals {
  region                           = lookup(var.json_input, "region", "East US")
  machine_type                     = lookup(var.json_input, "machine_type", "Standard_D2ds_v5")
  accelerated_networking           = lookup(var.json_input, "accelerated_networking", true)
  run_id                           = lookup(var.json_input, "run_id", "123456")
  public_key_path                  = lookup(var.json_input, "public_key_path", "")
  vm_count_override                = lookup(var.json_input, "vm_count_override", 0)
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
  data_disk_count                  = lookup(var.json_input, "data_disk_count", 1)
  storage_account_tier             = lookup(var.json_input, "storage_account_tier", "")
  storage_account_kind             = lookup(var.json_input, "storage_account_kind", "")
  storage_account_replication_type = lookup(var.json_input, "storage_account_replication_type", "")
  storage_share_enabled_protocol   = lookup(var.json_input, "storage_share_enabled_protocol", null)
  # storage_share_quota              = lookup(var.json_input, "storage_share_quota", null)
  # storage_share_access_tier        = lookup(var.json_input, "storage_share_access_tier", null)

  tags = {
    "owner"             = lookup(var.json_input, "owner", "github_actions")
    "scenario"          = "${var.scenario_type}-${var.scenario_name}"
    "creation_time"     = timestamp()
    "deletion_due_time" = timeadd(timestamp(), var.deletion_delay)
    "run_id"            = local.run_id
  }

  network_config_map          = { for network in var.network_config_list : network.role => network }
  loadbalancer_config_map     = { for loadbalancer in var.loadbalancer_config_list : loadbalancer.role => loadbalancer }
  appgateway_config_map       = { for appgateway in var.appgateway_config_list : appgateway.role => appgateway }
  proximity_group_config_map  = { for group in var.proximity_group_config_list : group.name => group }
  agc_config_map              = { for agc in var.agc_config_list : agc.role => agc }
  aks_config_map              = { for aks in var.aks_config_list : aks.role => aks }
  aks_cluster_oidc_issuer_map = { for aks in var.aks_config_list : aks.role => module.aks[aks.role].aks_cluster_oidc_issuer }
  aks_cluster_kubeconfig_list = [for aks in var.aks_config_list : module.aks[aks.role].aks_cluster_kubeconfig_path]
  expanded_vm_config_list = flatten([
    for vm in var.vm_config_list : [
      for i in range(local.vm_count_override > 0 ? local.vm_count_override : vm.count) : {
        role                           = vm.role
        vm_name                        = (local.vm_count_override > 0 ? local.vm_count_override : vm.count) > 1 ? "${vm.vm_name}-${i + 1}" : vm.vm_name
        nic_name                       = (local.vm_count_override > 0 ? local.vm_count_override : vm.count) > 1 ? "${vm.nic_name}-${i + 1}" : vm.nic_name
        admin_username                 = vm.admin_username
        info_column_name               = vm.info_column_name
        zone                           = vm.zone
        source_image_reference         = vm.source_image_reference
        create_vm_extension            = vm.create_vm_extension
        proximity_placement_group_name = vm.proximity_placement_group_name
      }
    ]
  ])
  vm_config_map                          = { for vm in local.expanded_vm_config_list : vm.vm_name => vm }
  vmss_config_map                        = { for vmss in var.vmss_config_list : vmss.vmss_name => vmss }
  nic_backend_pool_association_map       = { for config in var.nic_backend_pool_association_list : config.nic_name => config }
  all_nics                               = merge([for network in var.network_config_list : module.virtual_network[network.role].nics]...)
  all_subnets                            = merge([for network in var.network_config_list : module.virtual_network[network.role].subnets]...)
  all_loadbalancer_backend_address_pools = { for key, lb in module.load_balancer : "${key}-lb-pool" => lb.lb_pool_id }
  all_vms                                = { for vm in local.expanded_vm_config_list : vm.vm_name => module.virtual_machine[vm.vm_name].vm }
  all_proximity_groups                   = { for group in var.proximity_group_config_list : group.name => module.proximity_placement_group[group.name].proximity_placement_group_id }
  aks_cli_config_map                     = { for aks in var.aks_cli_config_list : aks.role => aks }
}

terraform {
  required_version = ">=1.5.6"
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "<= 3.93.0"
    }
    random = {
      source  = "hashicorp/random"
      version = ">=3.1.0"
    }

    helm = {
      source  = "hashicorp/helm"
      version = "<= 2.13.1"
    }
  }
}

provider "azurerm" {
  features {}
}

provider "helm" {
  kubernetes {
    config_paths = local.aks_cluster_kubeconfig_list
  }

  registry {
    url      = "oci://mcr.microsoft.com"
    username = ""
    password = ""
  }
}

module "public_ips" {
  source                = "./public-ip"
  resource_group_name   = local.run_id
  location              = local.region
  public_ip_config_list = var.public_ip_config_list
  pip_count_override    = local.vm_count_override
  tags                  = local.tags
}

module "virtual_network" {
  for_each = local.network_config_map

  source                 = "./network"
  network_config         = each.value
  resource_group_name    = local.run_id
  location               = local.region
  accelerated_networking = local.accelerated_networking
  public_ips             = module.public_ips.pip_ids
  nic_count_override     = local.vm_count_override
  tags                   = local.tags
}

module "proximity_placement_group" {
  for_each = local.proximity_group_config_map

  source              = "./proximity-placement-group"
  name                = each.value.name
  tags                = local.tags
  resource_group_name = local.run_id
  location            = local.region
}

module "aks" {
  for_each = local.aks_config_map

  source              = "./aks"
  resource_group_name = local.run_id
  location            = local.region
  subnet_id           = try(local.all_subnets[each.value.subnet_name], null)
  aks_config          = each.value
  tags                = local.tags
  vnet_id             = try(module.virtual_network[each.value.role].vnet_id, null)
  subnets             = try(local.all_subnets, null)
}

module "aks-cli" {
  for_each = local.aks_cli_config_map

  source              = "./aks-cli"
  resource_group_name = local.run_id
  location            = local.region
  aks_cli_config      = each.value
  tags                = local.tags
}

module "load_balancer" {
  for_each = local.loadbalancer_config_map

  source              = "./load-balancer"
  resource_group_name = local.run_id
  location            = local.region
  loadbalancer_config = each.value
  public_ip_id        = each.value.public_ip_name == null ? null : module.public_ips.pip_ids[each.value.public_ip_name]
  is_internal_lb      = each.value.is_internal_lb == null ? false : each.value.is_internal_lb
  subnet_id           = each.value.is_internal_lb == null ? "" : local.all_subnets[each.value.subnet_name]
  tags                = local.tags
}

module "appgateway" {
  for_each = local.appgateway_config_map

  source              = "./app-gateway"
  appgateway_config   = each.value
  resource_group_name = local.run_id
  location            = local.region
  subnet_id           = local.all_subnets[each.value.subnet_name]
  public_ip_id        = module.public_ips.pip_ids[each.value.public_ip_name]
  tags                = local.tags
}

module "agc" {
  for_each = local.agc_config_map

  source                  = "./agc"
  agc_config              = each.value
  resource_group_name     = local.run_id
  location                = local.region
  association_subnet_id   = local.all_subnets[each.value.association_subnet_name]
  tags                    = local.tags
  aks_cluster_oidc_issuer = local.aks_cluster_oidc_issuer_map[each.value.role]
  depends_on              = [module.aks]
}

module "data_disk" {
  count = var.data_disk_config == null ? 0 : local.data_disk_count

  source                         = "./data-disk"
  resource_group_name            = local.run_id
  location                       = local.region
  data_disk_name                 = "${var.data_disk_config.name_prefix}-${count.index}"
  tags                           = local.tags
  data_disk_storage_account_type = local.data_disk_storage_account_type
  data_disk_size_gb              = local.data_disk_size_gb
  data_disk_iops_read_write      = local.data_disk_iops_read_write
  data_disk_mbps_read_write      = local.data_disk_mbps_read_write
  data_disk_iops_read_only       = local.data_disk_iops_read_only
  data_disk_mbps_read_only       = local.data_disk_mbps_read_only
  data_disk_tier                 = local.data_disk_tier
  zone                           = strcontains(lower(local.data_disk_storage_account_type), "_zrs") ? null : var.data_disk_config.zone
}

module "virtual_machine" {
  for_each = local.vm_config_map

  source                       = "./virtual-machine"
  name                         = each.value.vm_name
  resource_group_name          = local.run_id
  location                     = local.region
  vm_sku                       = local.machine_type
  nic                          = local.all_nics[each.value.nic_name]
  vm_config                    = each.value
  public_key                   = file(local.public_key_path)
  user_data_path               = local.user_data_path
  tags                         = local.tags
  ultra_ssd_enabled            = local.ultra_ssd_enabled
  proximity_placement_group_id = each.value.proximity_placement_group_name != null ? local.all_proximity_groups[each.value.proximity_placement_group_name] : null
  depends_on                   = [module.proximity_placement_group]
}

module "virtual_machine_scale_set" {
  for_each = local.vmss_config_map

  source                = "./virtual-machine-scale-set"
  name                  = each.value.vmss_name
  resource_group_name   = local.run_id
  location              = local.region
  vm_sku                = local.machine_type
  subnet_id             = local.all_subnets[each.value.subnet_name]
  lb_pool_id            = local.all_loadbalancer_backend_address_pools[each.value.loadbalancer_pool_name]
  ip_configuration_name = each.value.ip_configuration_name
  vmss_config           = each.value
  public_key            = file(local.public_key_path)
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
  count = try(var.data_disk_config.vm_name, null) != null ? local.data_disk_count : 0

  managed_disk_id    = module.data_disk[count.index].data_disk.id
  virtual_machine_id = local.all_vms[var.data_disk_config.vm_name].id
  lun                = count.index
  caching            = (local.data_disk_caching == null || local.data_disk_caching == "") ? "ReadOnly" : local.data_disk_caching
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
  resource_group_name              = local.run_id
  location                         = local.region
  storage_account_tier             = local.storage_account_tier
  storage_account_kind             = local.storage_account_kind
  storage_account_replication_type = local.storage_account_replication_type
  enable_https_traffic_only        = local.storage_share_enabled_protocol == "NFS" ? false : true
  tags                             = local.tags

  # don't use terraform to create fileshare now, we are not able to delete the fileshare when it has network_rule set
  # storage_share_config = var.storage_account_file_share_name == null ? null : {
  #   name             = var.storage_account_file_share_name
  #   quota            = local.storage_share_quota
  #   access_tier      = local.storage_share_access_tier
  #   enabled_protocol = local.storage_share_enabled_protocol
  # }

  storage_blob_config = var.blob_config == null ? null : {
    container_name   = var.blob_config.container_name
    container_access = var.blob_config.container_access
    blob_name        = var.blob_config.blob_name
    blob_type        = var.blob_config.blob_type
    source_file_path = "${local.user_data_path}/${var.blob_config.source_file_name}"
  }
}

module "privatelink" {
  source = "./private-link"

  count = var.private_link_conf == null ? 0 : 1

  resource_group_name = local.run_id
  location            = local.region

  pls_name       = var.private_link_conf.pls_name
  pls_subnet_id  = local.all_subnets[var.private_link_conf.pls_subnet_name]
  pls_lb_fipc_id = module.load_balancer[var.private_link_conf.pls_loadbalance_role].lb_fipc_id

  pe_name      = var.private_link_conf.pe_name
  pe_subnet_id = local.all_subnets[var.private_link_conf.pe_subnet_name]

  tags = local.tags
}

module "private_endpoint" {
  source = "./private-endpoint"

  count = var.pe_config == null ? 0 : 1

  resource_group_name = local.run_id
  location            = local.region
  tags                = local.tags

  pe_subnet_id                   = local.all_subnets[var.pe_config.pe_subnet_name]
  private_connection_resource_id = module.storage_account[0].storage_account.id

  pe_config = var.pe_config
}
