locals {
  region                            = lookup(var.json_input, "region", "East US")
  run_id                            = lookup(var.json_input, "run_id", "123456")
  aks_sku_tier                      = lookup(var.json_input, "aks_sku_tier", null)
  aks_kubernetes_version            = lookup(var.json_input, "aks_kubernetes_version", null)
  aks_network_policy                = lookup(var.json_input, "aks_network_policy", null)
  aks_network_dataplane             = lookup(var.json_input, "aks_network_dataplane", null)
  aks_cli_system_node_pool          = lookup(var.json_input, "aks_cli_system_node_pool", null)
  aks_cli_user_node_pool            = lookup(var.json_input, "aks_cli_user_node_pool", null)
  aks_custom_headers                = lookup(var.json_input, "aks_custom_headers", [])
  k8s_machine_type                  = lookup(var.json_input, "k8s_machine_type", null)
  k8s_os_disk_type                  = lookup(var.json_input, "k8s_os_disk_type", null)
  aks_aad_enabled                   = lookup(var.json_input, "aks_aad_enabled", false)
  enable_apiserver_vnet_integration = lookup(var.json_input, "enable_apiserver_vnet_integration", false)
  public_key_path                   = lookup(var.json_input, "public_key_path", null)
  ssh_public_key                    = local.public_key_path != null ? (fileexists(local.public_key_path) ? file(local.public_key_path) : null) : null

  tags = merge(
    var.tags,
    {
      "owner"             = var.owner
      "scenario"          = "${var.scenario_type}-${var.scenario_name}"
      "creation_time"     = timestamp()
      "deletion_due_time" = timeadd(timestamp(), var.deletion_delay)
      "run_id"            = local.run_id
      "SkipAKSCluster"    = "1"
    }
  )

  network_config_map = { for network in var.network_config_list : network.role => network }

  route_table_config_map = { for rt in var.route_table_config_list : rt.name => rt }

  aks_cli_custom_config_path = "${path.cwd}/../../../scenarios/${var.scenario_type}/${var.scenario_name}/config/aks_custom_config.json"

  all_subnets    = merge([for network in var.network_config_list : module.virtual_network[network.role].subnets]...)
  all_key_vaults = merge([for kv_name, kv in module.key_vault : { (kv_name) = kv.key_vaults }]...)
  updated_aks_config_list = length(var.aks_config_list) > 0 ? [
    for aks in var.aks_config_list : merge(
      aks,
      {
        sku_tier           = local.aks_sku_tier != null ? local.aks_sku_tier : aks.sku_tier
        kubernetes_version = local.aks_kubernetes_version != null ? local.aks_kubernetes_version : aks.kubernetes_version
      }
    )
  ] : []

  aks_config_map = length(local.updated_aks_config_list) == 0 ? { for aks in var.aks_config_list : aks.role => aks } : { for aks in local.updated_aks_config_list : aks.role => aks }

  updated_aks_cli_config_list = length(var.aks_cli_config_list) > 0 ? [
    for aks in var.aks_cli_config_list : merge(
      aks,
      {
        sku_tier                          = local.aks_sku_tier != null ? local.aks_sku_tier : aks.sku_tier
        kubernetes_version                = local.aks_kubernetes_version != null ? local.aks_kubernetes_version : aks.kubernetes_version
        aks_custom_headers                = length(local.aks_custom_headers) > 0 ? local.aks_custom_headers : aks.aks_custom_headers
        default_node_pool                 = local.aks_cli_system_node_pool != null ? local.aks_cli_system_node_pool : aks.default_node_pool
        extra_node_pool                   = local.aks_cli_user_node_pool != null ? local.aks_cli_user_node_pool : aks.extra_node_pool
        enable_apiserver_vnet_integration = local.enable_apiserver_vnet_integration
      }
    )
  ] : []

  aks_cli_config_map = { for aks in local.updated_aks_cli_config_list : aks.role => aks }

  key_vault_config_map = { for kv in var.key_vault_config_list : kv.name => kv }

  jumpbox_config_map = { for jumpbox in var.jumpbox_config_list : jumpbox.role => jumpbox }
}

provider "azurerm" {
  features {
    key_vault {
      purge_soft_delete_on_destroy    = true
      recover_soft_deleted_key_vaults = false
    }
  }
}

module "public_ips" {
  source                = "./public-ip"
  resource_group_name   = local.run_id
  location              = local.region
  public_ip_config_list = var.public_ip_config_list
  tags                  = local.tags
}

module "virtual_network" {
  for_each = local.network_config_map

  source              = "./network"
  network_config      = each.value
  resource_group_name = local.run_id
  location            = local.region
  public_ips          = module.public_ips.pip_ids
  tags                = local.tags
}

module "dns_zones" {

  source              = "./dns-zone"
  resource_group_name = local.run_id
  dns_zones           = var.dns_zones
  tags                = local.tags
}

module "firewall" {
  source = "./firewall"

  firewall_config_list = var.firewall_config_list
  subnets_map          = local.all_subnets
  public_ips_map       = module.public_ips.pip_ids
  resource_group_name  = local.run_id
  location             = local.region
  tags                 = local.tags

  depends_on = [module.virtual_network]
}

module "route_table" {
  for_each = local.route_table_config_map

  source = "./route-table"

  route_table_config   = each.value
  resource_group_name  = local.run_id
  location             = local.region
  subnets_ids          = local.all_subnets
  firewall_private_ips = module.firewall.firewall_private_ips
  public_ips           = module.public_ips.pip_ids
  tags                 = local.tags

  depends_on = [module.virtual_network, module.firewall]
}

module "key_vault" {
  for_each = local.key_vault_config_map

  source              = "./key-vault"
  resource_group_name = local.run_id
  location            = local.region
  key_vault_config    = each.value
  tags                = local.tags
}

module "aks" {
  for_each = local.aks_config_map

  source              = "./aks"
  resource_group_name = local.run_id
  location            = local.region
  aks_config          = each.value
  tags                = local.tags
  subnet_id           = try(local.all_subnets[each.value.subnet_name], null)
  vnet_id             = try(module.virtual_network[each.value.role].vnet_id, null)
  subnets             = try(local.all_subnets, null)
  k8s_machine_type    = local.k8s_machine_type
  k8s_os_disk_type    = local.k8s_os_disk_type
  network_dataplane   = local.aks_network_dataplane
  network_policy      = local.aks_network_policy
  dns_zones           = try(module.dns_zones.dns_zone_ids, null)
  aks_aad_enabled     = local.aks_aad_enabled
  key_vaults          = local.all_key_vaults
  depends_on          = [module.route_table, module.virtual_network]
}

module "aks-cli" {
  for_each = local.aks_cli_config_map

  source                     = "./aks-cli"
  resource_group_name        = local.run_id
  location                   = local.region
  aks_cli_config             = each.value
  tags                       = local.tags
  subnets_map                = local.all_subnets
  aks_cli_custom_config_path = local.aks_cli_custom_config_path
  key_vaults                 = local.all_key_vaults
  aks_aad_enabled            = local.aks_aad_enabled
  depends_on                 = [module.route_table, module.virtual_network]
}

module "jumpbox" {
  for_each = local.jumpbox_config_map

  source              = "./jumpbox"
  resource_group_name = local.run_id
  location            = local.region
  tags                = local.tags
  ssh_public_key      = local.ssh_public_key
  jumpbox_config      = each.value
  public_ips_map      = module.public_ips.pip_ids
  subnets_map         = local.all_subnets

  # Ensure AKS cluster is created before jumpbox tries to look it up for RBAC
  depends_on = [module.aks, module.aks-cli]
}
